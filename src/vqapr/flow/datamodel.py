"""A datamodel run: the same loop as a strategy's, with compute where the callback was.

Record `148` closes `docs/issues/059`. A DataModel used to be run by `materialize()`: its own loop
over a list of instants from a spec file, every row of every evaluation held in memory until the
end, one parquet and a lineage file written at once, and a `record.json` of its own kind. It is a
run now, registered under `runs:` like a strategy run, frozen by the same preflight, walked by the
same `OccurrenceFlow`, recorded under the same `runs/<run-id>/` directory -- with a
`DataModelPhase` in the callback's place and no execution or valuation phase, because a datamodel
sees no account and passes through no venue (architecture 4.4).

What leaves the process: the sessions' rows, typed as they come and held in memory, land as one
parquet file under `.vqapr/materialized/<dataset_id>/` when the last session completes
(`docs/issues/087`; a file per session was a physical write per loop), and the dataset registers
right after, through the registration path every other dataset takes. A run that fails first
leaves no readable output -- a partial dataset registers with nothing -- and a re-run starts clean.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from vqapr.authoring import DataModel
from vqapr.calls import DataModelContext
from vqapr.data.datasets import DatasetRegistration, Grain, validate
from vqapr.data.sources import SourceSpec
from vqapr.data.store import AccessRecord
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.domain.identifiers import instrument_id
from vqapr.domain.values import Row, Rows, normalize_rows, require_tz_aware
from vqapr.flow.frozen import FrozenDataModel, FrozenRun
from vqapr.flow.loop import OccurrenceFlow
from vqapr.workspace import Workspace

MATERIALIZED_DIRECTORY = "materialized"
"""Under `.vqapr/`: one directory per output dataset, one parquet file (`all.parquet`) once
the run has registered it; spill parts beside it only while a large run is still computing."""

OUTPUT_CODES = "datamodel.output"
"""The prefix of the output-contract codes, `datamodel.output.<breach>`: what `compute` returned
is not something the framework can use (422, under the `run` stage)."""


class LookAheadDetected(AssertionError):
    """A read returned a row that was not knowable at the instant that read it.

    Its own exception type because this is not a bug in the caller's declaration -- it is the
    package having violated its own point-in-time boundary, and the two want different responses.
    """


def derived_available_at(
    evaluation_time: datetime,
    accesses: Sequence[AccessRecord],
) -> datetime:
    """Stamp when a derived value was knowable from the rows actually consumed.

    Lived in `flow/stamping.py` while two producers stamped derived rows; the publication path
    went with `flow/materialize.py` (one-shape campaign Step 4), and this is the one caller left.

    The answer is always `evaluation_time`, and the loop that used to search for a later instant
    was unreachable. It was unreachable *contingently*, not by construction: `scan.py` binds
    every observation query with `WHERE available_at <= evaluation_time`, so no access can carry a
    later one. Loosen that bound and the loop becomes live again.

    Deleting it would have satisfied the dead-code rule and quietly removed the only thing watching
    for the failure. That failure is uniquely dangerous here because look-ahead **improves**
    correlations: a leak makes every downstream number look better, so neither the count gate nor
    `compare_factors.py` would flag it, and nothing else in the stack is looking. A silent
    improvement is the hardest kind of wrong to notice.

    So the branch is gone and the invariant it depended on is now checked instead. It costs one
    comparison per access on a path that already iterates them, and it fails loudly the moment the
    PIT bound stops holding.
    """
    stamped = require_tz_aware(evaluation_time, name="evaluation_time")
    for access in accesses:
        observed = access.max_available_at
        if observed is not None and observed > stamped:
            raise LookAheadDetected(
                "a read returned a row newer than the instant that read it: "
                f"{getattr(access, 'dataset_id', '<unknown dataset>')} carried "
                f"{observed.isoformat()} at evaluation_time {stamped.isoformat()}. "
                "Every observation query binds available_at <= evaluation_time; reaching this "
                "means that bound was loosened, and look-ahead improves correlations rather than "
                "breaking them, so no downstream gate would have caught it."
            )
    return stamped


def refusal(
    stage: Stage,
    code: str,
    requirement: str,
    observed: str,
    *,
    status: Status,
    fix: str,
    retry: str,
    cause: BaseException | None = None,
    source: FailureSource | None = None,
    examples: Sequence[str] = (),
    example_total: int | None = None,
) -> VqaprError:
    """One refusal, one failure.

    `examples`/`example_total` are optional because most refusals here are structural -- a wrong
    field set, a forged column -- and a structural check has no offending *value* to quote. A
    check on row contents does, and passes them: `Failure.bounded` truncates to `MAX_EXAMPLES`
    and `example_total` carries the count before truncation (record `121`). `cause` is the
    exception in hand, when there is one, so the whole traceback rides on the failure.
    """
    return VqaprError(
        stage=stage,
        failures=[
            Failure.bounded(
                code,
                requirement,
                status=status,
                observed=observed,
                fix=fix,
                cause=cause,
                source=source,
                examples=examples,
                example_total=example_total,
            )
        ],
        mutation=False,
        retry_precondition=retry,
    )


def validated_output(
    raw: object,
    *,
    value_fields: Sequence[str],
    selected_instruments: Sequence[str],
) -> Rows:
    """One evaluation's rows, as the contract admits them, or the refusal that names the breach.

    Two content checks collect instead of failing fast. `SKILL.md` promises that a check on row
    *contents* quotes up to five offending values and reports how many there were before
    truncation; raising inside the loop cannot honour that (issue 032). The per-row *structural*
    checks still raise on the first offender: a row whose field set is wrong, or whose instrument
    will not parse, has no content to judge yet.
    """
    try:
        rows = normalize_rows(raw)
    except (TypeError, ValueError) as error:
        raise refusal(
            Stage.RUN,
            f"{OUTPUT_CODES}.rows_invalid",
            "DataModel output must contain portable finite scalar rows",
            f"{type(error).__name__}: {error}",
            status=Status.CONTRACT,
            fix=(
                "return only finite scalar values (no NaN/inf, no nested objects) from "
                "DataModel.compute"
            ),
            cause=error,
            retry="fix DataModel.compute output, register the component again, then retry",
        ) from error

    expected = {"instrument", *value_fields}
    selected = set(selected_instruments)
    seen: set[str] = set()
    unrequested: list[str] = []
    unrequested_rows = 0
    duplicated: list[str] = []
    duplicate_rows = 0
    for index, row in enumerate(rows):
        actual = set(row)
        if "available_at" in actual:
            raise refusal(
                Stage.RUN,
                f"{OUTPUT_CODES}.available_at_owned",
                "DataModel output must not set package-owned available_at",
                f"row {index} fields={sorted(actual)}",
                status=Status.CONTRACT,
                fix="drop available_at from the row dict returned by DataModel.compute",
                retry="remove available_at from DataModel output, then retry",
            )
        if actual != expected:
            raise refusal(
                Stage.RUN,
                f"{OUTPUT_CODES}.fields_invalid",
                f"every output row must contain exactly {sorted(expected)}",
                f"row {index} fields={sorted(actual)}",
                status=Status.CONTRACT,
                fix=f"return exactly {sorted(expected)} on every row from DataModel.compute",
                retry="return exactly the declared output fields, then retry",
            )
        try:
            instrument = str(instrument_id(row["instrument"]))
        except (TypeError, ValueError) as error:
            raise refusal(
                Stage.RUN,
                f"{OUTPUT_CODES}.instrument_invalid",
                "every output row must identify one valid requested instrument",
                f"row {index}: {error}",
                status=Status.CONTRACT,
                fix="return only valid instrument identities from DataModel.compute",
                cause=error,
                retry="return valid requested instrument identities, then retry",
            ) from error
        if instrument not in selected:
            unrequested_rows += 1
            if instrument not in unrequested:
                unrequested.append(instrument)
            # Not entered into `seen`: an unrequested instrument is one violation, not also a
            # duplicate one.
            continue
        if instrument in seen:
            duplicate_rows += 1
            if instrument not in duplicated:
                duplicated.append(instrument)
            continue
        seen.add(instrument)
    if unrequested:
        raise refusal(
            Stage.RUN,
            f"{OUTPUT_CODES}.instrument_unrequested",
            "DataModel output instruments must come from the run's universe",
            (
                f"{len(unrequested)} unrequested instrument(s) across {unrequested_rows} "
                f"of {len(rows)} output row(s)"
            ),
            status=Status.CONTRACT,
            fix="only emit rows for instruments the run declares under `instruments:`",
            retry="return values only for requested instruments, then retry",
            examples=unrequested,
            example_total=len(unrequested),
        )
    if duplicated:
        raise refusal(
            Stage.RUN,
            f"{OUTPUT_CODES}.instrument_duplicate",
            "DataModel output must contain at most one row per instrument per evaluation",
            (
                f"{len(duplicated)} repeated instrument(s) across {duplicate_rows} "
                f"extra of {len(rows)} output row(s)"
            ),
            status=Status.CONTRACT,
            fix="emit at most one row per instrument per evaluation from DataModel.compute",
            retry="deduplicate DataModel output, then retry",
            examples=duplicated,
            example_total=len(duplicated),
        )
    return rows


def output_directory(project_root: str | Path, dataset_id: str) -> Path:
    """Where one datamodel run's chunks land: `.vqapr/materialized/<dataset_id>/`."""
    return Path(project_root) / ".vqapr" / MATERIALIZED_DIRECTORY / dataset_id


def output_source_id(dataset_id: str) -> str:
    return f"materialized-{dataset_id}"


COMPACT_FILENAME = "all.parquet"
"""The one file a finished table or dataset is: written when the run ends, after which any spill
part beside it is stale input. Shared with `vqapr.flow.record` (`docs/issues/087`)."""

SPILL_BYTES = 256 * 1024 * 1024
"""The safety valve, for both writers: buffered Arrow bytes above this are written as one spill
part. A run of a few million rows would otherwise hold them all; at this size a part is a few
seconds of disk and the buffer never exceeds a quarter gigabyte. It is not a flush cadence -- a
run below the line writes nothing until it ends -- and a hard kill loses at most this much."""


class DataModelOutput:
    """One output dataset, typed a session at a time in memory and written once at the end.

    The directory is the source: `SourceSpec` reads every parquet beneath a directory. Sessions
    are held as Arrow tables and land as one `all.parquet` when the run registers
    (`docs/issues/087`:
    a file per session was a physical write per loop); above `spill_bytes` a spill part is
    written first and folded into the compact file at the end. Each file is written beside its
    target and moved into place, so a reader listing the directory never opens a file whose
    footer is not there yet. A run that fails before registering leaves nothing readable -- a
    partial dataset registers with nothing and `open()` clears it on retry.
    """

    def __init__(
        self,
        project_root: str | Path,
        layer: FrozenDataModel,
        *,
        run_id: str | None = None,
        spill_bytes: int = SPILL_BYTES,
    ) -> None:
        self._root = Path(project_root)
        self._layer = layer
        self._run_id = run_id
        self._directory = output_directory(project_root, layer.dataset_id)
        self._schema: pa.Schema | None = None
        self._parts = 0
        self._sessions = 0
        self._rows = 0
        self._buffered: list[pa.Table] = []
        self._buffered_bytes = 0
        self._spill_bytes = spill_bytes

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def rows(self) -> int:
        return self._rows

    def open(self) -> None:
        """Claim the output directory, clearing what a dead run left there.

        Preflight already refused a dataset id that is registered, so a directory found here
        belongs to a run that never registered -- killed, or refused at registration -- and a
        retry means starting clean, not appending to it.
        """
        if self._directory.exists():
            shutil.rmtree(self._directory)

    def append(self, rows: Sequence[Row]) -> None:
        """Type one session's rows and hold them; they land at `register`, or at a spill."""
        self._sessions += 1
        if not rows:
            return
        try:
            table = pa.Table.from_pylist([dict(row) for row in rows], schema=self._schema)
        except (pa.ArrowException, TypeError, ValueError) as error:
            if self._schema is None:
                raise refusal(
                    Stage.RUN,
                    f"{OUTPUT_CODES}.rows_invalid",
                    "a session's rows must be portable scalars pyarrow can type",
                    f"{type(error).__name__}: {error}",
                    status=Status.CONTRACT,
                    fix="return only finite scalar values from DataModel.compute",
                    cause=error,
                    retry="fix DataModel.compute output, then retry",
                ) from error
            # The schema is whatever pyarrow inferred from the first non-empty session, and this
            # session's rows did not fit it. That is all this code knows. It used to call this
            # `type_drift` and tell the author to "return the same scalar type on every session"
            # -- which was already true in the run that filed `docs/issues/079`: the type was
            # `Decimal` throughout and what moved was its SCALE, inferred as 27 decimal places
            # from one session's ratios and 28 from the next's. A refusal that names a cause it
            # did not measure sends the reader the wrong way; pyarrow's own sentence, beside the
            # schema the first session fixed, is the accurate statement (owner ruling
            # 2026-09-05: the data and its types are the author's, and the framework asserts
            # nothing it cannot tell).
            established = ", ".join(f"{field.name}: {field.type}" for field in self._schema)
            raise refusal(
                Stage.RUN,
                f"{OUTPUT_CODES}.schema_mismatch",
                "every session's rows must fit the schema the first non-empty session established",
                f"{type(error).__name__}: {error}; established schema: {established}",
                status=Status.CONTRACT,
                fix=(
                    "return values that fit that schema on every session. A Decimal's precision "
                    "and scale are part of its type, so for a continuous quantity return float, "
                    "and where you need Decimal, quantize it to one scale in compute"
                ),
                cause=error,
                retry="fix DataModel.compute output, then retry",
            ) from error
        if self._schema is None:
            self._schema = table.schema
        self._buffered.append(table)
        self._buffered_bytes += table.nbytes
        self._rows += len(rows)
        if self._buffered_bytes >= self._spill_bytes:
            self._write(self._directory / f"{self._parts:06d}.parquet", self._buffered)
            self._parts += 1
            self._buffered = []
            self._buffered_bytes = 0

    def _write(self, target: Path, tables: Sequence[pa.Table]) -> None:
        """Several sessions as one complete file, beside its target and moved into place."""
        staging = target.with_name(f".{target.name}.tmp")
        try:
            # Created by the first file, not at open: a run refused before any row leaves no
            # empty directory behind to be mistaken for an output.
            self._directory.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.concat_tables(tables), staging, compression="zstd", use_dictionary=False
            )
            os.replace(staging, target)
        except (OSError, pa.ArrowException) as error:
            raise refusal(
                Stage.RECORD,
                "datamodel.chunk_failed",
                "a session's rows must land on the project filesystem",
                f"{type(error).__name__}: {error}",
                status=Status.UNAVAILABLE,
                fix=f"check filesystem permissions and free space for {self._directory}",
                cause=error,
                retry="repair project filesystem access, then retry",
                source=FailureSource(file=str(target)),
            ) from error

    def _seal(self) -> None:
        """Everything as `all.parquet`: the spill parts, then what is buffered; parts removed
        once the compact file is in place, so an interruption between the two repeats nothing
        for a reader that prefers the compact file (`read_table` does; a duckdb glob sees both
        only inside that window)."""
        parts = sorted(self._directory.glob("[0-9]*.parquet")) if self._directory.is_dir() else []
        tables = [pq.read_table(part) for part in parts] + self._buffered
        if not tables:
            return
        self._write(self._directory / COMPACT_FILENAME, tables)
        for part in parts:
            part.unlink()
        self._buffered = []
        self._buffered_bytes = 0

    def register(self, workspace: Workspace) -> DatasetRegistration:
        """Register the directory as the declared dataset, through the one registration path.

        A refused registration removes the chunks: the workspace is unchanged, and a retry after
        the fix starts from an empty directory rather than beside a stale one.
        """
        if self._rows == 0:
            self._discard()
            raise refusal(
                Stage.RUN,
                f"{OUTPUT_CODES}.empty",
                "a datamodel run must produce at least one output row",
                f"all {self._sessions} session(s) returned zero rows",
                status=Status.CONTRACT,
                fix=(
                    "a lookback longer than the available history makes every window short and "
                    "every session empty: check that each input dataset holds enough rows before "
                    "the first session. Otherwise widen the instruments or the sessions, or fix "
                    "DataModel.compute to emit rows"
                ),
                retry="fix input coverage or DataModel output, then retry",
            )
        source_id = output_source_id(self._layer.dataset_id)
        registration = DatasetRegistration.of(
            self._layer.dataset_id,
            source_id,
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={field: field for field in self._layer.value_fields},
            # Stated by the producer, not derived: one row per instrument per session is what
            # `validated_output` admits, so what lands IS that grain.
            grain=Grain.INSTRUMENT_INSTANT,
        )
        if self._run_id is not None:
            # The dataset names the run that wrote it (`docs/issues/082`): known here and
            # nowhere later, since the registration is the only thing that outlives this run.
            registration = registration.with_producer(self._run_id)
        source = SourceSpec.of(source_id, self._directory)
        try:
            # The rows land here, once, and only now: a dataset that is registered is complete.
            self._seal()
            diagnosis, _, registration = validate(registration, source)
            diagnosis.raise_if_failed()
            with Workspace.transaction(workspace.project_root) as transaction:
                transaction.register_dataset(registration, source)
        except Exception:
            self._discard()
            raise
        return registration

    def _discard(self) -> None:
        shutil.rmtree(self._directory, ignore_errors=True)


@dataclass(frozen=True, slots=True)
class DataModelTrace:
    """What one session's compute did: when it ran, what it read, what it produced."""

    occurrence: OperationOccurrence
    evaluation_time: datetime
    output_available_at: datetime
    row_count: int
    accesses: tuple[AccessRecord, ...]


@dataclass(frozen=True, slots=True)
class DataModelResult:
    """A finished datamodel run: one trace per session, and the dataset it registered."""

    occurrences: tuple[DataModelTrace, ...]
    rows: int
    output_path: Path
    registration: DatasetRegistration | None = None


class DataModelPhase:
    """One session's compute: window, rows, stamp, chunk."""

    def __init__(
        self,
        *,
        frozen_run: FrozenRun,
        layer: FrozenDataModel,
        model: DataModel,
        window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        output: DataModelOutput,
    ) -> None:
        self._frozen_run = frozen_run
        self._layer = layer
        self._model = model
        self._window_for_occurrence = window_for_occurrence
        self._output = output
        # Resolved once for the whole run: `inputs()` is a declaration, not a per-session
        # decision, and re-resolving it each time would let it differ between sessions.
        self._reads = model.inputs()

    def dispatch(self, occurrence: OperationOccurrence) -> DataModelTrace:
        window = self._window_for_occurrence(occurrence)
        evaluation_time = window.evaluation_time
        try:
            raw = self._model.compute(DataModelContext(window, self._reads))
        except VqaprError:
            raise
        except Exception as error:
            raise refusal(
                Stage.RUN,
                "datamodel.compute_failed",
                "DataModel.compute must complete for every session",
                f"{occurrence.occurrence_id}: {type(error).__name__}: {error}",
                status=Status.CRASHED,
                fix=(
                    "fix the exception raised inside DataModel.compute for this session; the "
                    "traceback is in `cause`"
                ),
                cause=error,
                retry="fix the DataModel or its declared input sufficiency, then retry",
            ) from error
        rows = validated_output(
            raw,
            value_fields=self._layer.value_fields,
            selected_instruments=self._frozen_run.instruments,
        )
        available_at = derived_available_at(evaluation_time, window.accesses)
        stamped: list[Row] = []
        for row in rows:
            record: Row = {"available_at": available_at, "instrument": row["instrument"]}
            record.update({field: row[field] for field in self._layer.value_fields})
            stamped.append(record)
        self._output.append(stamped)
        return DataModelTrace(
            occurrence=occurrence,
            evaluation_time=evaluation_time,
            output_available_at=available_at,
            row_count=len(rows),
            accesses=window.accesses,
        )


class DataModelFlow(OccurrenceFlow):
    """Walk one datamodel's sessions: compute at each, chunk the rows, register at the end."""

    def __init__(
        self,
        frozen_run: FrozenRun,
        layer: FrozenDataModel,
        model: DataModel,
        *,
        window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        output: DataModelOutput,
        on_progress: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(frozen_run, FrozenRun):
            raise TypeError("frozen_run must be a FrozenRun")
        if not isinstance(layer, FrozenDataModel) or layer not in frozen_run.datamodels:
            raise TypeError("layer must be one of the frozen run's datamodels")
        if not isinstance(model, DataModel):
            raise TypeError("model must be a DataModel")
        if not callable(window_for_occurrence):
            raise TypeError("window_for_occurrence must be callable")
        if not isinstance(output, DataModelOutput):
            raise TypeError("output must be a DataModelOutput")
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("a datamodel run requires a frozen boundary")
        self._start_cutoff = cutoff
        self._static_occurrences = frozen_run.dispatch_order(layer)
        self._on_progress = on_progress
        self._output = output
        self._phase = DataModelPhase(
            frozen_run=frozen_run,
            layer=layer,
            model=model,
            window_for_occurrence=window_for_occurrence,
            output=output,
        )

    def _start(self, cutoff: datetime) -> None:
        self._output.open()

    def _dispatch_static(self, occurrence: OperationOccurrence) -> DataModelTrace:
        return self._phase.dispatch(occurrence)

    def _finish(self, traces: tuple[object, ...]) -> DataModelResult:
        return DataModelResult(
            occurrences=tuple(traces),  # type: ignore[arg-type]
            rows=self._output.rows,
            output_path=self._output.directory,
        )


__all__ = [
    "MATERIALIZED_DIRECTORY",
    "DataModelFlow",
    "DataModelOutput",
    "DataModelPhase",
    "DataModelResult",
    "DataModelTrace",
    "output_directory",
    "output_source_id",
    "validated_output",
]
