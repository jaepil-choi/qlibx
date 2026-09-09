"""What a datamodel run leaves behind: the output contract, and the dataset it registers.

The sessions' rows, typed as they come and held in memory, land as one parquet file under
`.vqapr/materialized/<dataset_id>/` when the last session completes (`docs/issues/archive/087`; a
file per session was a physical write per loop), and the dataset registers right after, through the
registration path every other dataset takes. A run that fails first leaves no readable output -- a
partial dataset registers with nothing -- and a re-run starts clean.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.scan import (
    DECLARABLE_FIELD_TYPE_NAMES,
    DECLARABLE_FIELD_TYPES,
    ColumnType,
    column_type_of_arrow,
)
from vqapr.data.sources import SourceSpec
from vqapr.data.store import AccessRecord
from vqapr.domain.errors import Failure, FailureSource, Stage, Status, VqaprError
from vqapr.domain.identifiers import instrument_id
from vqapr.domain.shapes import Grain, Row, Rows, normalize_rows
from vqapr.domain.values import require_tz_aware
from vqapr.project.store import Workspace
from vqapr.record import COMPACT_FILENAME, SPILL_BYTES

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
            raw_instrument = row["instrument"]
            if not isinstance(raw_instrument, str):
                raise TypeError(
                    f"instrument_id must be a string, got {type(raw_instrument).__name__}"
                )
            instrument = str(instrument_id(raw_instrument))
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


class RunOutput:
    """One output dataset, typed a session at a time in memory and written once at the end.

    The directory is the source: `SourceSpec` reads every parquet beneath a directory. Sessions
    are held as Arrow tables and land as one `all.parquet` when the run registers
    (`docs/issues/archive/087`:
    a file per session was a physical write per loop); above `spill_bytes` a spill part is
    written first and folded into the compact file at the end. Each file is written beside its
    target and moved into place, so a reader listing the directory never opens a file whose
    footer is not there yet. A run that fails before registering leaves nothing readable -- a
    partial dataset registers with nothing and `open()` clears it on retry.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        writes: str,
        value_fields: Sequence[str],
        run_id: str | None = None,
        record_ref: str | None = None,
        spill_bytes: int = SPILL_BYTES,
    ) -> None:
        # Not a `FrozenDataModel`: a strategy publishes through this door too (design §2), and
        # what both hand over is the name the run writes and the fields each row carries.
        # `record_ref` is the member's `<component_id>@<fp8>`, so the dataset can say which
        # version wrote it (`docs/issues/091`).
        self._root = Path(project_root)
        self._writes = writes
        self._value_fields = tuple(value_fields)
        self._run_id = run_id
        self._record_ref = record_ref
        self._directory = output_directory(project_root, writes)
        self._schema: pa.Schema | None = None
        self._field_types: dict[str, ColumnType] = {}
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

    def _declarable(self, schema: pa.Schema) -> dict[str, ColumnType]:
        """The field types this output will declare, read off what the first session wrote.

        The producer states the types, as any author does (`docs/issues/archive/088`), and states
        them from the schema it is about to write so that registration's DESCRIBE agrees by
        construction. A type that no declaration may carry -- a `Decimal` value field above all --
        is refused here, at the first session, rather than after every session has run.
        """
        declared: dict[str, ColumnType] = {}
        offending: list[str] = []
        for name in self._value_fields:
            column_type = column_type_of_arrow(schema.field(name).type)
            if column_type not in DECLARABLE_FIELD_TYPES:
                offending.append(f"{name}: {schema.field(name).type} ({column_type.value})")
            declared[name] = column_type
        if offending:
            raise refusal(
                Stage.RUN,
                f"{OUTPUT_CODES}.field_type",
                "every value field must be a type a dataset can declare: "
                f"{DECLARABLE_FIELD_TYPE_NAMES}",
                "; ".join(offending),
                status=Status.CONTRACT,
                fix=(
                    "return float for a continuous quantity and int for a count. A Decimal "
                    "reaches a model as `Decimal` while a float reaches it as `float`, and a "
                    "dataset carries one numeric type per field"
                ),
                retry="fix DataModel.compute output, then retry",
            )
        return declared

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
            # `type_drift` and tell the author to "return the same scalar type on every session" --
            # which was already true in the run that filed `docs/issues/archive/079`: the type was
            # `Decimal` throughout and what moved was its SCALE, inferred as 27 decimal places from
            # one session's ratios and 28 from the next's. A refusal that names a cause it did not
            # measure sends the reader the wrong way; pyarrow's own sentence, beside the schema the
            # first session fixed, is the accurate statement (owner ruling 2026-09-05: the data and
            # its types are the author's, and the framework asserts nothing it cannot tell).
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
            self._field_types = self._declarable(table.schema)
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
        source_id = output_source_id(self._writes)
        registration = DatasetRegistration.of(
            self._writes,
            source_id,
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={field: field for field in self._value_fields},
            # Stated by the producer from what it wrote (`_declarable`), as the grain below is.
            field_types=self._field_types,
            # Stated by the producer, not derived: one row per instrument per session is what
            # `validated_output` admits, so what lands IS that grain.
            grain=Grain.INSTRUMENT_INSTANT,
        )
        if self._run_id is not None:
            # The dataset names the run that wrote it (`docs/issues/archive/082`) and the record
            # -- the component version -- that did (`docs/issues/091`): known here and nowhere
            # later, since the registration is the only thing that outlives this run.
            registration = registration.with_producer(self._run_id, self._record_ref)
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


__all__ = [
    "MATERIALIZED_DIRECTORY",
    "OUTPUT_CODES",
    "LookAheadDetected",
    "RunOutput",
    "derived_available_at",
    "output_directory",
    "output_source_id",
    "refusal",
    "validated_output",
]
