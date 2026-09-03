"""Run a registered DataModel and publish its values as a registered dataset."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq

from vqapr.authoring import Hold
from vqapr.data.datasets import DatasetRegistration, Grain, validate
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, FailureSource, VqaprError
from vqapr.domain.identifiers import DatasetId, dataset_id
from vqapr.domain.rows import Row
from vqapr.evidence.artifacts import CallbackEvidence
from vqapr.evidence.tables import FLOW_ENVELOPE_FIELDS
from vqapr.flow.simulation import AcceptedIntent, SimulationResult, callback_evidence
from vqapr.flow.stamping import derived_available_at
from vqapr.workspace import Workspace

_INPUT_STAGE = "materialize.input"
_OUTPUT_STAGE = "materialize.output"
_PUBLISH_STAGE = "materialize.publish"


_RESERVED_FIELDS = frozenset({"available_at", "instrument"})


@dataclass(frozen=True, slots=True)
class AllocationPublicationSpec:
    """Where a run's allocation is published and under which value field."""

    dataset_id: DatasetId
    value_field: str

    @classmethod
    def of(cls, raw_dataset_id: str, *, value_field: str = "weight") -> AllocationPublicationSpec:
        if (
            not isinstance(value_field, str)
            or not value_field
            or any(character.isspace() for character in value_field)
        ):
            raise ValueError("value_field must be a non-empty string without whitespace")
        if value_field in _RESERVED_FIELDS:
            raise ValueError(f"value_field is package-owned: {value_field}")
        return cls(dataset_id(raw_dataset_id), value_field)


@dataclass(frozen=True, slots=True)
class RunRecordSpec:
    """Where a run's recorded table is published and under which value fields.

    A recorded table is a run's own account of what it did, published so a later run can reuse it
    (canon 9.2). The five Flow-stamped envelope columns ride as ordinary declared value fields:
    without them the publication would drop the which-run, whose and at-what-time obligation that
    PRD 9.4 places on a stored record, which is the whole reason to publish it.

    ``available_at`` and ``instrument`` stay package-owned, exactly as they do for the other two
    specs. The envelope fields are a *different* reserved set and are deliberately declarable here:
    they name the row's provenance rather than its position, and the two sets are disjoint.
    """

    dataset_id: DatasetId
    table_id: str
    value_fields: tuple[str, ...]
    availability_field: str = "event_time"
    """Which column says when this table's rows became knowable. **Per table, not per package.**

    The two candidates mean different things and only one is right for a given table:

    ``observed_at`` is a MEASUREMENT clock -- when the value was seen. `vqapr.account` declares it,
    because a NAV is a measurement of a book at an instant, and dating that series by anything else
    labels every value by when it was written rather than when it was true. Measured once, that
    mislabelling took a factor correlation from 0.93 to 0.02 (F-009).

    ``event_time`` is a DECISION clock -- when the row happened. `allocation` and `vqapr.weight`
    declare no `observed_at` at all, because the row IS the decision; there is nothing separate to
    have observed.

    So this is declared rather than hardcoded. `publish_run_record` is generic over any recorded
    table (`materialize.py:797`), and a package-wide column would be right for one table and wrong
    for the next -- silently, because both produce a plausible date.
    """

    @classmethod
    def of(
        cls,
        raw_dataset_id: str,
        *,
        table_id: str,
        value_fields: tuple[str, ...],
        availability_field: str = "event_time",
    ) -> RunRecordSpec:
        if not isinstance(table_id, str) or not table_id.strip():
            raise ValueError("table_id must be a non-empty string")
        if not isinstance(value_fields, tuple) or not value_fields:
            raise ValueError("value_fields must be a non-empty tuple")
        if any(
            not isinstance(field, str) or not field or any(c.isspace() for c in field)
            for field in value_fields
        ):
            raise ValueError("value_fields must be non-empty strings without whitespace")
        if len(set(value_fields)) != len(value_fields):
            raise ValueError("value_fields must be unique")
        reserved = sorted(set(value_fields) & _RESERVED_FIELDS)
        if reserved:
            # The same guard the other two specs apply. A record that could name its own
            # available_at would let a producer choose its own stamp on the one publication path
            # that exists to prove it did not.
            raise ValueError(f"value_fields are package-owned: {reserved}")
        missing = sorted(FLOW_ENVELOPE_FIELDS - set(value_fields))
        if missing:
            # Canon states the five Flow-stamped columns ride as declared value fields, because a
            # record without them drops the which-run, whose and at-what-time obligation that is
            # the reason to publish it at all. Requiring them here keeps the contract enforced
            # rather than merely written down.
            raise ValueError(f"a run record must declare the Flow envelope fields: {missing}")
        clock = availability_field.strip()
        if clock not in value_fields:
            # The column that dates the series has to be one the record actually carries, or the
            # publication would stamp from a field nobody wrote.
            raise ValueError(
                f"availability_field {clock!r} must be one of the declared value fields: "
                f"{', '.join(sorted(value_fields))}"
            )
        return cls(dataset_id(raw_dataset_id), table_id.strip(), value_fields, clock)


@dataclass(frozen=True, slots=True)
class RunRecordResult:
    """The registered dataset a later run subscribes to, plus its lineage receipt."""

    registration: object
    output_path: Path
    lineage_path: Path
    row_count: int


@dataclass(frozen=True, slots=True)
class AllocationPublicationResult:
    """The registered dataset a later run subscribes to, plus its lineage receipt."""

    registration: DatasetRegistration
    output_path: Path
    lineage_path: Path
    occurrences: int
    row_count: int


def _error(
    stage: str,
    code: str,
    requirement: str,
    observed: str,
    *,
    fix: str,
    explain: ExplainTopic,
    family: FailureFamily = FailureFamily.DATA,
    retry: str,
    source: FailureSource | None = None,
    examples: Sequence[str] = (),
    example_total: int | None = None,
) -> VqaprError:
    """One refusal, one failure.

    `examples`/`example_total` are optional because most refusals here are structural -- a wrong
    field set, a forged column -- and a structural check has no offending *value* to quote. A
    check on row contents does, and passes them: `Failure.bounded` truncates to `MAX_EXAMPLES`
    and `example_total` carries the count before truncation, which is the whole point of the
    field. See `docs/implementations/121`.
    """
    return VqaprError(
        stage=stage,
        family=family,
        failures=[
            Failure.bounded(
                code,
                requirement,
                observed=observed,
                fix=fix,
                explain=explain,
                source=source,
                examples=examples,
                example_total=example_total,
            )
        ],
        mutation=False,
        retry_precondition=retry,
    )


def _json_scalar(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize lineage scalar {type(value).__name__}")


def _lineage_envelope(
    *,
    operation: str,
    dataset_id: str,
    source_id: str,
    value_fields: Sequence[str],
    instruments: Sequence[str],
) -> dict[str, object]:
    """The keys every publication shares, whatever produced it.

    ``operation`` discriminates the provenance block a caller adds on top. The alternative -- making
    both callers emit the same key set -- would force a fabricated empty component block onto run
    allocations, which is the drift this split exists to prevent.
    """
    return {
        "schema_version": 1,
        "operation": operation,
        "output": {
            "dataset_id": dataset_id,
            "source_id": source_id,
            "value_fields": list(value_fields),
        },
        "instruments": list(instruments),
    }


def _safe_stem(value: str) -> str:
    return quote(value, safe="-_.")


def _publish_new(staged: Path, target: Path) -> None:
    """Atomically expose a new file without ever replacing an existing target."""
    try:
        os.link(staged, target)
        staged.unlink()
    except FileExistsError as error:
        raise _error(
            _PUBLISH_STAGE,
            f"{_PUBLISH_STAGE}.path_exists",
            "materialization must not overwrite an existing physical output",
            str(target),
            fix="choose a new dataset_id, or delete the orphaned file at the reported path",
            explain=ExplainTopic.PUBLICATION,
            source=FailureSource(file=str(target)),
            family=FailureFamily.PUBLICATION,
            retry="choose a new output dataset_id or recover the orphaned file, then retry",
        ) from error
    except OSError as error:
        raise _error(
            _PUBLISH_STAGE,
            f"{_PUBLISH_STAGE}.file_failed",
            "staged materialization files must publish on the project filesystem",
            f"{type(error).__name__}: {error}",
            fix=(
                f"check filesystem permissions and free space for {target}; the write failed "
                "after the staged output was built, so nothing was published"
            ),
            explain=ExplainTopic.PUBLICATION,
            family=FailureFamily.PUBLICATION,
            retry="repair project filesystem access, then retry",
            # The sibling FileExistsError branch above already names the target; a permissions or
            # disk-space failure is exactly as much about that path, so it says so too.
            source=FailureSource(file=str(target)),
        ) from error


def _stage_and_publish(
    *,
    workspace: Workspace,
    project_root: str | Path,
    dataset_id: str,
    source_id: str,
    value_fields: Sequence[str],
    rows: Sequence[Row],
    payload: Mapping[str, object],
) -> tuple[DatasetRegistration, Path, Path]:
    """Stage, validate, atomically expose, and register one derived dataset.

    Both publication callers share this body rather than each owning a copy: a second publication
    path would be a second publication authority, and they would drift.
    """
    root = Path(project_root)
    output_directory = root / ".vqapr" / "materialized"
    stem = _safe_stem(dataset_id)
    output_path = output_directory / f"{stem}.parquet"
    lineage_path = output_directory / f"{stem}.lineage.json"
    if output_path.exists() or lineage_path.exists():
        raise _error(
            _PUBLISH_STAGE,
            f"{_PUBLISH_STAGE}.path_exists",
            "materialization must not overwrite an existing physical output",
            f"output={output_path.exists()}, lineage={lineage_path.exists()}",
            fix="choose a new output dataset_id, or delete the orphaned output/lineage files",
            explain=ExplainTopic.PUBLICATION,
            source=FailureSource(file=str(output_path)),
            family=FailureFamily.PUBLICATION,
            retry="choose a new output dataset_id or recover the orphaned files, then retry",
        )

    with tempfile.TemporaryDirectory(prefix=".materialize-", dir=workspace.path.parent) as raw_tmp:
        temporary_directory = Path(raw_tmp)
        temporary_output = temporary_directory / "output.parquet"
        temporary_lineage = temporary_directory / "lineage.json"
        try:
            table = pa.Table.from_pylist([dict(row) for row in rows])
            pq.write_table(
                table,
                temporary_output,
                compression="zstd",
                use_dictionary=False,
                write_statistics=True,
            )
            temporary_lineage.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    indent=2,
                    default=_json_scalar,
                )
                + "\n",
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError, pa.ArrowException) as error:
            raise _error(
                _PUBLISH_STAGE,
                f"{_PUBLISH_STAGE}.staging_failed",
                "derived rows and lineage must serialize to staged artifacts",
                f"{type(error).__name__}: {error}",
                fix=(
                    "return only JSON/Arrow-serializable scalar values, and check "
                    "filesystem access"
                ),
                explain=ExplainTopic.PUBLICATION,
                family=FailureFamily.PUBLICATION,
                retry="fix output scalar compatibility or filesystem access, then retry",
            ) from error

        candidate_registration = DatasetRegistration.of(
            dataset_id,
            source_id,
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={field: field for field in value_fields},
            # Stated by the publisher, not derived: the shared publication authority keys on
            # (available_at, instrument) and refuses a duplicate before exposure, so what it
            # publishes IS that grain.
            grain=Grain.INSTRUMENT_INSTANT,
        )
        candidate_source = SourceSpec.of(source_id, temporary_output)
        diagnosis, _, candidate_registration = validate(candidate_registration, candidate_source)
        diagnosis.raise_if_failed()

        output_directory.mkdir(parents=True, exist_ok=True)
        published_output = False
        published_lineage = False
        try:
            _publish_new(temporary_output, output_path)
            published_output = True
            _publish_new(temporary_lineage, lineage_path)
            published_lineage = True
            final_source = SourceSpec.of(source_id, output_path)
            workspace.register_dataset(candidate_registration, final_source)
        except Exception:
            if published_lineage:
                lineage_path.unlink(missing_ok=True)
            if published_output:
                output_path.unlink(missing_ok=True)
            raise

    return candidate_registration, output_path, lineage_path


def publish_run_allocation(
    project_root: str | Path,
    spec: AllocationPublicationSpec,
    evidences: SimulationResult | Sequence[CallbackEvidence],
) -> AllocationPublicationResult:
    """Publish a completed run's allocations as an ordinary registered dataset.

    Takes what ``run()`` returned, or the callback evidence already extracted from it. Both are
    accepted because ``publish_run_record`` sits beside this function with the same shape and
    takes the result; a caller who passed the result to one and evidence to the other was reading
    the signatures right and still got a bare ``TypeError`` from inside a ``tuple()`` call.

    The stamp is derived, never chosen: ``available_at`` comes from
    :func:`derived_available_at` over the callback's own recorded accesses, so a producer cannot
    advertise its decision earlier than the inputs that justified it. A consumer evaluating before
    that stamp therefore sees nothing, which is what keeps a chained run honest.

    Weights are written on the canonical optimizer grid, not on any vendor scale, so a subscriber
    reads back exactly the value the accepted intent carried.
    """
    if not isinstance(spec, AllocationPublicationSpec):
        raise TypeError("spec must be an AllocationPublicationSpec")
    collected = (
        callback_evidence(evidences)
        if isinstance(evidences, SimulationResult)
        else tuple(evidences)
    )
    for evidence in collected:
        missing = [
            name
            for name in (
                "run_identity",
                "cutoff",
                "strategy_accesses",
                "decision",
                # Read below for the sources section and the state path. Guarding them
                # here keeps a wrong-shaped caller from publishing an empty provenance
                # section instead of failing at the input stage.
                "actual_source_refs",
                "committed_model_state_ref",
            )
            if not hasattr(evidence, name)
        ]
        if missing:
            # Refuse a wrong-typed input here rather than letting it fall through the decline path,
            # where it would surface as "every occurrence declined to allocate" and point the
            # operator at strategy behaviour instead of at the caller's own contract violation.
            raise _error(
                _INPUT_STAGE,
                f"{_INPUT_STAGE}.evidence_invalid",
                "every published evidence must carry callback authority, inputs, and a decision",
                f"{type(evidence).__name__} is missing {missing}",
                fix="publish CallbackEvidence objects from run()'s own result, not hand-built ones",
                explain=ExplainTopic.COMPONENT_CONTRACT,
                retry="publish from the run's callback evidence, then retry",
            )
    if not collected:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.empty",
            "publishing a run allocation requires at least one callback evidence",
            "no evidence supplied",
            fix="run the strategy to completion before calling publish_run_allocation",
            explain=ExplainTopic.RUN_PRECONDITION,
            retry="run the strategy first, then publish its result",
        )

    workspace = Workspace.open(project_root)
    if any(item.dataset_id == spec.dataset_id for item in workspace.datasets):
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.dataset_exists",
            "published allocation dataset_id must be new",
            str(spec.dataset_id),
            # Deliberately does NOT name `vqapr run --force`. That flag replaces a RUN RECORD, not
            # a registration: it recursively removes `<store_root>/runs/<run_id>/` and leaves this
            # dataset exactly where it is. Naming it here would send a reader to delete the wrong
            # artifact and then meet this same refusal again -- and SKILL.md tells agents to act
            # on `fix` first, so the instruction would be followed before it was doubted.
            fix=(
                f"publish under a dataset_id that is not registered, or remove the existing "
                f"{spec.dataset_id} registration from the workspace first"
            ),
            explain=ExplainTopic.WORKSPACE_STATE,
            retry="choose a new output dataset_id, then retry",
        )

    rows: list[Row] = []
    instruments: set[str] = set()
    run_identities: set[str] = set()
    occurrences = 0
    for evidence in collected:
        decision = evidence.decision
        if isinstance(decision, Hold):
            # An occurrence that declined to allocate has no allocation, and inventing an empty one
            # would misrepresent the run.
            continue
        # A run records its decision as the Flow's accepted pending item, which carries the intent
        # alongside the execution target it was bound to. Unwrapping here is what lets a real run
        # publish; reading `.targets` off the wrapper would refuse every genuine callback and admit
        # only a hand-built stand-in.
        intent = decision.intent if isinstance(decision, AcceptedIntent) else decision
        targets = getattr(intent, "targets", None)
        if targets is None:
            raise _error(
                _OUTPUT_STAGE,
                f"{_OUTPUT_STAGE}.decision_invalid",
                "a callback decision must be Hold or an economic intent",
                type(decision).__name__,
                fix="return Hold or Rebalance from the strategy's decide()",
                explain=ExplainTopic.COMPONENT_CONTRACT,
                retry="publish from a strategy that emits economic intents, then retry",
            )
        available_at = derived_available_at(evidence.cutoff, tuple(evidence.strategy_accesses))
        run_identities.add(str(evidence.run_identity))
        occurrences += 1
        for target in targets:
            weight = getattr(target, "weight", None)
            if weight is None:
                raise _error(
                    _OUTPUT_STAGE,
                    f"{_OUTPUT_STAGE}.not_weighted",
                    "only weight-economics intents can publish an allocation",
                    f"{target.instrument_id} carries a quantity",
                    fix=(
                        "switch the strategy to weight economics, or publish quantities "
                        "another way"
                    ),
                    explain=ExplainTopic.COMPONENT_CONTRACT,
                    retry="publish from a weight-economics strategy, then retry",
                )
            instruments.add(str(target.instrument_id))
            rows.append(
                {
                    "available_at": available_at,
                    "instrument": str(target.instrument_id),
                    spec.value_field: weight,
                }
            )

    if not rows:
        raise _error(
            _OUTPUT_STAGE,
            f"{_OUTPUT_STAGE}.empty",
            "publishing a run allocation must produce at least one row",
            "every occurrence declined to allocate",
            fix="rerun the strategy with inputs that produce at least one allocation decision",
            explain=ExplainTopic.RUN_PRECONDITION,
            retry="publish a run that produced at least one intent, then retry",
        )

    # Provenance comes from what the Flow observed, never from what the intent claimed. An intent's
    # own refs are every source the window served, so emitting those would name an observation
    # dataset a member. A reader identifies members one hop out instead, by whether a source's own
    # envelope records an allocation operation.
    sources = sorted(
        {
            str(getattr(ref, "source_id", ref))
            for evidence in collected
            for ref in evidence.actual_source_refs
        }
    )
    # State movement across the callback body, package-computed and unforgeable. It attests that
    # state moved -- necessary but not sufficient for path dependence, per canon 9.2.
    state_path = sorted(
        {
            "moved"
            if evidence.committed_model_state_ref != evidence.current_model_state_ref
            else "constant"
            for evidence in collected
        }
    )

    source_id = f"allocation-{spec.dataset_id}"
    payload = _lineage_envelope(
        operation="strategy.allocation",
        dataset_id=str(spec.dataset_id),
        source_id=source_id,
        value_fields=(spec.value_field,),
        instruments=sorted(instruments),
    )
    payload["run"] = {
        "run_identity": sorted(run_identities),
        "occurrences": occurrences,
        "row_count": len(rows),
        "sources": sources,
        "state_path": state_path,
    }
    registration, output_path, lineage_path = _stage_and_publish(
        workspace=workspace,
        project_root=project_root,
        dataset_id=str(spec.dataset_id),
        source_id=source_id,
        value_fields=(spec.value_field,),
        rows=sorted(rows, key=lambda row: (row["available_at"], row["instrument"])),
        payload=payload,
    )
    return AllocationPublicationResult(
        registration=registration,
        output_path=output_path,
        lineage_path=lineage_path,
        occurrences=occurrences,
        row_count=len(rows),
    )


def publish_run_record(
    project_root: str | Path,
    spec: RunRecordSpec,
    result: object,
    *,
    instrument_field: str = "instrument",
) -> RunRecordResult:
    """Publish one recorded table from a finished run as an ordinary registered dataset.

    This is the **third caller** of the one shared publication authority, alongside ``materialize``
    and ``publish_run_allocation`` -- not a second authority. Canon 9.2 fixes what it preserves:

    * ``available_at`` is derived, never declared, so a producer cannot advertise its record
      earlier than the occurrence that justified it.
    * ``event_time`` and ``available_at`` are **two clocks and stay two columns**. The first is the
      occurrence the row was written at, the second is when the row becomes visible; PRD 9.4
      forbids collapsing them.
    * The five Flow-stamped envelope columns ride as declared value fields, carrying which run,
      whose, and at what time.
    * One row per key. Several stages of one measurement are distinct **columns** on one row, never
      repeated rows, because the shared authority keys on ``(available_at, instrument)`` and
      refuses a duplicate before exposure.
    """
    project = Path(project_root)
    workspace = Workspace.open(project)
    if not isinstance(spec, RunRecordSpec):
        raise TypeError("spec must be a RunRecordSpec")

    recorded = getattr(getattr(result, "final_state", None), "recorder_rows", None)
    if recorded is None:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.result_invalid",
            "publishing a run record requires a run result carrying recorder rows",
            f"{type(result).__name__} exposes no final_state.recorder_rows",
            fix="pass the object run() returned, not a hand-built or partial result",
            explain=ExplainTopic.COMPONENT_CONTRACT,
            retry="publish from the value run() returned, then retry",
        )
    source_rows = tuple(recorded.get(spec.table_id, ()))
    if not source_rows:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.empty",
            "the run recorded no rows for this table",
            f"table {spec.table_id!r} is absent or empty",
            fix=(
                f"have the strategy record at least one row to table {spec.table_id!r} "
                "during the run"
            ),
            explain=ExplainTopic.RUN_PRECONDITION,
            retry="declare the table on the Strategy and record rows, then retry",
        )

    rows: list[dict[str, object]] = []
    instruments: set[str] = set()
    for row in source_rows:
        for required in (instrument_field, "event_time"):
            if required not in row:
                raise _error(
                    _INPUT_STAGE,
                    f"{_INPUT_STAGE}.fields_invalid",
                    "every recorded row must carry the instrument column and the Flow envelope",
                    f"row is missing {required!r}",
                    fix=f"record {required!r} on every row written to table {spec.table_id!r}",
                    explain=ExplainTopic.COMPONENT_CONTRACT,
                    retry="declare the instrument column on the table, then retry",
                )
        instrument = str(row[instrument_field])
        instruments.add(instrument)
        # Per table, from the spec's declared clock. `vqapr.account` dates by `observed_at`
        # because a NAV is a measurement; `allocation` dates by `event_time` because the row is
        # the decision. Hardcoding either is right for one table and silently wrong for the next.
        if spec.availability_field not in row:
            raise _error(
                _INPUT_STAGE,
                f"{_INPUT_STAGE}.fields_invalid",
                (
                    f"table {spec.table_id!r} declares {spec.availability_field!r} as the column "
                    "that says when its rows became knowable, so every row must carry it"
                ),
                f"a row has no {spec.availability_field!r} column at all",
                fix=(
                    f"record {spec.availability_field!r} on every row of {spec.table_id!r}, or "
                    "declare a different availability_field on the RunRecordSpec"
                ),
                explain=ExplainTopic.COMPONENT_CONTRACT,
                retry="record the declared availability column on every row, then retry",
            )

        # A NULL measurement clock is a real state, not a malformed row, and the distinction is
        # the whole reason this is not simply `row[field] or row["event_time"]`.
        #
        # `observed_at` is null on an occurrence that took no mark -- a session where the venue
        # published no price at or before the instant, so the book was genuinely not measured.
        # Measured on the real factor table: 2,368,704 of 4,738,842 rows. Refusing them would
        # make the per-table clock unusable on `vqapr.account`, which is the one table it exists
        # for; publishing them undated would be worse.
        #
        # So a row that was never measured is dated by when it happened. That is not a silent
        # substitution of one clock for the other: it is the honest answer for a row whose
        # measurement clock has nothing to say, and it applies only where the declared clock is
        # explicitly null rather than absent.
        knowable = row[spec.availability_field]
        if knowable is None:
            knowable = row["event_time"]
        published: dict[str, object] = {
            "available_at": knowable,
            "instrument": instrument,
        }
        for field in spec.value_fields:
            if field not in row:
                raise _error(
                    _INPUT_STAGE,
                    f"{_INPUT_STAGE}.fields_invalid",
                    "every declared value field must be present on every recorded row",
                    f"row is missing {field!r}",
                    fix=f"record {field!r} on every row written to table {spec.table_id!r}",
                    explain=ExplainTopic.COMPONENT_CONTRACT,
                    retry="record the declared fields on every row, then retry",
                )
            published[field] = row[field]
        rows.append(published)

    source_id = f"record-{spec.dataset_id}"
    payload = _lineage_envelope(
        operation="run.record",
        dataset_id=str(spec.dataset_id),
        source_id=source_id,
        value_fields=spec.value_fields,
        instruments=sorted(instruments),
    )
    payload["record"] = {
        "table_id": spec.table_id,
        "row_count": len(rows),
        "run_identity": sorted({str(row["run_id"]) for row in source_rows if "run_id" in row}),
    }
    registration, output_path, lineage_path = _stage_and_publish(
        workspace=workspace,
        project_root=project,
        dataset_id=str(spec.dataset_id),
        source_id=source_id,
        value_fields=spec.value_fields,
        rows=sorted(rows, key=lambda row: (row["available_at"], row["instrument"])),
        payload=payload,
    )
    return RunRecordResult(
        registration=registration,
        output_path=output_path,
        lineage_path=lineage_path,
        row_count=len(rows),
    )
