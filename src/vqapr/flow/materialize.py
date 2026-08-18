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

from vqapr.data.datasets import DatasetRegistration, validate
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.sources import SourceSpec
from vqapr.data.windows import AccessRecord
from vqapr.domain.errors import Failure, FailureFamily, VqaprError
from vqapr.domain.identifiers import DatasetId, dataset_id, instrument_id
from vqapr.domain.rows import Row, Rows, normalize_rows
from vqapr.domain.timestamps import require_tz_aware
from vqapr.evidence.artifacts import CallbackEvidence
from vqapr.evidence.tables import FLOW_ENVELOPE_FIELDS
from vqapr.extension.loading import load_data_model
from vqapr.flow.simulation import AcceptedIntent
from vqapr.flow.stamping import derived_available_at
from vqapr.flow.views import data_model_window
from vqapr.models.contexts import DataModelContext
from vqapr.models.strategy_model import NoDecision
from vqapr.workspace import Workspace

_INPUT_STAGE = "materialize.input"
_COMPUTE_STAGE = "materialize.compute"
_OUTPUT_STAGE = "materialize.output"
_PUBLISH_STAGE = "materialize.publish"
_RESERVED_FIELDS = frozenset({"available_at", "instrument"})


@dataclass(frozen=True, slots=True)
class MaterializationSpec:
    dataset_id: DatasetId
    value_fields: tuple[str, ...]

    @classmethod
    def of(
        cls,
        raw_dataset_id: str,
        *,
        value_fields: Sequence[str],
    ) -> MaterializationSpec:
        fields = tuple(value_fields)
        if not fields:
            raise ValueError("value_fields must contain at least one field")
        if any(
            not isinstance(field, str)
            or not field
            or any(character.isspace() for character in field)
            for field in fields
        ):
            raise ValueError("value_fields must be non-empty strings without whitespace")
        if len(set(fields)) != len(fields):
            raise ValueError("value_fields must be unique")
        reserved = sorted(set(fields) & _RESERVED_FIELDS)
        if reserved:
            raise ValueError(f"value_fields are package-owned: {reserved}")
        return cls(dataset_id(raw_dataset_id), fields)


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

    @classmethod
    def of(
        cls, raw_dataset_id: str, *, table_id: str, value_fields: tuple[str, ...]
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
        return cls(dataset_id(raw_dataset_id), table_id.strip(), value_fields)


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


@dataclass(frozen=True, slots=True)
class MaterializationInvocation:
    evaluation_time: datetime
    output_available_at: datetime
    row_count: int
    accesses: tuple[AccessRecord, ...]


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    registration: DatasetRegistration
    output_path: Path
    lineage_path: Path
    invocations: tuple[MaterializationInvocation, ...]


def _error(
    stage: str,
    code: str,
    requirement: str,
    observed: str,
    *,
    family: FailureFamily = FailureFamily.DATA,
    retry: str,
) -> VqaprError:
    return VqaprError(
        stage=stage,
        family=family,
        failures=[Failure.bounded(code, requirement, observed=observed)],
        mutation=False,
        retry_precondition=retry,
    )


def _evaluation_times(values: Sequence[datetime]) -> tuple[datetime, ...]:
    try:
        selected = tuple(values)
    except TypeError as error:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.evaluation_times_invalid",
            "evaluation_times must be a finite sequence",
            f"{type(error).__name__}: {error}",
            retry="provide sorted unique timezone-aware evaluation times, then retry",
        ) from error
    try:
        for value in selected:
            require_tz_aware(value, name="evaluation_time")
    except (TypeError, ValueError) as error:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.evaluation_times_invalid",
            "every evaluation time must be timezone-aware",
            str(error),
            retry="provide sorted unique timezone-aware evaluation times, then retry",
        ) from error
    if not selected or len(set(selected)) != len(selected) or selected != tuple(sorted(selected)):
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.evaluation_times_invalid",
            "evaluation_times must be non-empty, strictly increasing, and unique",
            repr(selected),
            retry="provide sorted unique timezone-aware evaluation times, then retry",
        )
    return selected


def _instruments(values: Sequence[str]) -> tuple[str, ...]:
    try:
        selected = tuple(str(instrument_id(value)) for value in values)
    except (TypeError, ValueError) as error:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.instruments_invalid",
            "instruments must contain valid identities",
            str(error),
            retry="provide a non-empty unique instrument list, then retry",
        ) from error
    if not selected or len(set(selected)) != len(selected):
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.instruments_invalid",
            "instruments must be non-empty and unique",
            repr(selected),
            retry="provide a non-empty unique instrument list, then retry",
        )
    return selected


def _validated_output(
    raw: object,
    *,
    spec: MaterializationSpec,
    selected_instruments: tuple[str, ...],
) -> Rows:
    try:
        rows = normalize_rows(raw)
    except (TypeError, ValueError) as error:
        raise _error(
            _OUTPUT_STAGE,
            f"{_OUTPUT_STAGE}.rows_invalid",
            "DataModel output must contain portable finite scalar rows",
            f"{type(error).__name__}: {error}",
            retry="fix DataModel.compute output, register the component again, then retry",
        ) from error

    expected = {"instrument", *spec.value_fields}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        actual = set(row)
        if "available_at" in actual:
            raise _error(
                _OUTPUT_STAGE,
                f"{_OUTPUT_STAGE}.available_at_owned",
                "DataModel output must not set package-owned available_at",
                f"row {index} fields={sorted(actual)}",
                retry="remove available_at from DataModel output, then retry",
            )
        if actual != expected:
            raise _error(
                _OUTPUT_STAGE,
                f"{_OUTPUT_STAGE}.fields_invalid",
                f"every output row must contain exactly {sorted(expected)}",
                f"row {index} fields={sorted(actual)}",
                retry="return exactly the declared output fields, then retry",
            )
        try:
            instrument = str(instrument_id(row["instrument"]))
        except (TypeError, ValueError) as error:
            raise _error(
                _OUTPUT_STAGE,
                f"{_OUTPUT_STAGE}.instrument_invalid",
                "every output row must identify one valid requested instrument",
                f"row {index}: {error}",
                retry="return valid requested instrument identities, then retry",
            ) from error
        if instrument not in selected_instruments:
            raise _error(
                _OUTPUT_STAGE,
                f"{_OUTPUT_STAGE}.instrument_unrequested",
                "DataModel output instruments must come from the invocation input",
                instrument,
                retry="return values only for requested instruments, then retry",
            )
        if instrument in seen:
            raise _error(
                _OUTPUT_STAGE,
                f"{_OUTPUT_STAGE}.instrument_duplicate",
                "DataModel output must contain at most one row per instrument per evaluation",
                instrument,
                retry="deduplicate DataModel output, then retry",
            )
        seen.add(instrument)
    return rows


def _json_scalar(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize lineage scalar {type(value).__name__}")


def _lookback(access: AccessRecord) -> Mapping[str, object]:
    if isinstance(access.lookback, RowsLookback):
        return {"kind": "rows", "rows": access.lookback.rows}
    if isinstance(access.lookback, CalendarLookback):
        return {
            "kind": "calendar",
            "years": access.lookback.years,
            "months": access.lookback.months,
            "days": access.lookback.days,
            "timezone": access.lookback.timezone,
        }
    raise TypeError("unsupported lookback")


def _access_payload(access: AccessRecord) -> Mapping[str, object]:
    return {
        "consumer_id": access.consumer_id,
        "dataset_id": str(access.dataset_id),
        "fields": list(access.fields),
        "lookback": _lookback(access),
        "evaluation_time": access.evaluation_time.isoformat(),
        "instruments": list(access.instruments),
        "lower_bound": (access.lower_bound.isoformat() if access.lower_bound is not None else None),
        "actual_rows": {
            instrument: dict(sorted(counts.items()))
            for instrument, counts in sorted(access.actual_rows.items())
        },
        "max_available_at": (
            access.max_available_at.isoformat() if access.max_available_at is not None else None
        ),
    }


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


def _lineage_payload(
    *,
    component_id: str,
    fingerprint: str,
    source_id: str,
    spec: MaterializationSpec,
    instruments: tuple[str, ...],
    invocations: tuple[MaterializationInvocation, ...],
) -> Mapping[str, object]:
    payload = _lineage_envelope(
        operation="datamodel.materialize",
        dataset_id=str(spec.dataset_id),
        source_id=source_id,
        value_fields=spec.value_fields,
        instruments=instruments,
    )
    payload["component"] = {"component_id": component_id, "fingerprint": fingerprint}
    payload["invocations"] = [
        {
            "evaluation_time": invocation.evaluation_time.isoformat(),
            "output_available_at": invocation.output_available_at.isoformat(),
            "row_count": invocation.row_count,
            "accesses": [_access_payload(access) for access in invocation.accesses],
        }
        for invocation in invocations
    ]
    return payload


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
            family=FailureFamily.PUBLICATION,
            retry="choose a new output dataset_id or recover the orphaned file, then retry",
        ) from error
    except OSError as error:
        raise _error(
            _PUBLISH_STAGE,
            f"{_PUBLISH_STAGE}.file_failed",
            "staged materialization files must publish on the project filesystem",
            f"{type(error).__name__}: {error}",
            family=FailureFamily.PUBLICATION,
            retry="repair project filesystem access, then retry",
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
        )
        candidate_source = SourceSpec.of(source_id, temporary_output)
        diagnosis, _ = validate(candidate_registration, candidate_source)
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
    evidences: Sequence[CallbackEvidence],
) -> AllocationPublicationResult:
    """Publish a completed run's allocations as an ordinary registered dataset.

    The stamp is derived, never chosen: ``available_at`` comes from
    :func:`derived_available_at` over the callback's own recorded accesses, so a producer cannot
    advertise its decision earlier than the inputs that justified it. A consumer evaluating before
    that stamp therefore sees nothing, which is what keeps a chained run honest.

    Weights are written on the canonical optimizer grid, not on any vendor scale, so a subscriber
    reads back exactly the value the accepted intent carried.
    """
    if not isinstance(spec, AllocationPublicationSpec):
        raise TypeError("spec must be an AllocationPublicationSpec")
    collected = tuple(evidences)
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
                retry="publish from the run's callback evidence, then retry",
            )
    if not collected:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.empty",
            "publishing a run allocation requires at least one callback evidence",
            "no evidence supplied",
            retry="run the strategy first, then publish its result",
        )

    workspace = Workspace.open(project_root)
    if any(item.dataset_id == spec.dataset_id for item in workspace.datasets):
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.dataset_exists",
            "published allocation dataset_id must be new",
            str(spec.dataset_id),
            retry="choose a new output dataset_id, then retry",
        )

    rows: list[Row] = []
    instruments: set[str] = set()
    run_identities: set[str] = set()
    occurrences = 0
    for evidence in collected:
        decision = evidence.decision
        if isinstance(decision, NoDecision):
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
                "a callback decision must be NoDecision or an economic intent",
                type(decision).__name__,
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
            retry="publish from the value run() returned, then retry",
        )
    source_rows = tuple(recorded.get(spec.table_id, ()))
    if not source_rows:
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.empty",
            "the run recorded no rows for this table",
            f"table {spec.table_id!r} is absent or empty",
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
                    retry="declare the instrument column on the table, then retry",
                )
        instrument = str(row[instrument_field])
        instruments.add(instrument)
        published: dict[str, object] = {
            "available_at": row["event_time"],
            "instrument": instrument,
        }
        for field in spec.value_fields:
            if field not in row:
                raise _error(
                    _INPUT_STAGE,
                    f"{_INPUT_STAGE}.fields_invalid",
                    "every declared value field must be present on every recorded row",
                    f"row is missing {field!r}",
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


def materialize(
    project_root: str | Path,
    raw_component_id: str,
    spec: MaterializationSpec,
    *,
    evaluation_times: Sequence[datetime],
    instruments: Sequence[str],
) -> MaterializationResult:
    """Compute all evaluations first, then expose one complete registered parquet."""
    if not isinstance(spec, MaterializationSpec):
        raise TypeError("spec must be a MaterializationSpec")
    times = _evaluation_times(evaluation_times)
    selected_instruments = _instruments(instruments)
    workspace = Workspace.open(project_root)
    if any(item.dataset_id == spec.dataset_id for item in workspace.datasets):
        raise _error(
            _INPUT_STAGE,
            f"{_INPUT_STAGE}.dataset_exists",
            "materialization output dataset_id must be new",
            str(spec.dataset_id),
            retry="choose a new output dataset_id, then retry",
        )

    ref = workspace.component(raw_component_id)
    model = load_data_model(ref)
    requirements = model.requirements()
    stamped_rows: list[Row] = []
    invocation_records: list[MaterializationInvocation] = []
    for evaluation_time in times:
        window = data_model_window(
            workspace,
            evaluation_time=evaluation_time,
            instruments=selected_instruments,
            requirements=requirements,
        )
        try:
            raw_rows = model.compute(DataModelContext(window))
        except VqaprError:
            raise
        except Exception as error:
            raise _error(
                _COMPUTE_STAGE,
                f"{_COMPUTE_STAGE}.failed",
                "DataModel.compute must complete for every evaluation before publication",
                f"{type(error).__name__}: {error}",
                retry="fix the DataModel or its declared input sufficiency, then retry",
            ) from error
        rows = _validated_output(
            raw_rows,
            spec=spec,
            selected_instruments=selected_instruments,
        )
        available_at = derived_available_at(evaluation_time, window.accesses)
        for row in rows:
            stamped: Row = {
                "available_at": available_at,
                "instrument": row["instrument"],
            }
            stamped.update({field: row[field] for field in spec.value_fields})
            stamped_rows.append(stamped)
        invocation_records.append(
            MaterializationInvocation(
                evaluation_time=evaluation_time,
                output_available_at=available_at,
                row_count=len(rows),
                accesses=window.accesses,
            )
        )

    if not stamped_rows:
        raise _error(
            _OUTPUT_STAGE,
            f"{_OUTPUT_STAGE}.empty",
            "materialization must produce at least one output row",
            "all invocations returned zero rows",
            retry="fix input coverage or DataModel output, then retry",
        )

    source_id = f"materialized-{spec.dataset_id}"
    invocations = tuple(invocation_records)
    candidate_registration, output_path, lineage_path = _stage_and_publish(
        workspace=workspace,
        project_root=project_root,
        dataset_id=str(spec.dataset_id),
        source_id=source_id,
        value_fields=spec.value_fields,
        rows=stamped_rows,
        payload=_lineage_payload(
            component_id=str(ref.component_id),
            fingerprint=ref.fingerprint,
            source_id=source_id,
            spec=spec,
            instruments=selected_instruments,
            invocations=invocations,
        ),
    )

    return MaterializationResult(
        registration=candidate_registration,
        output_path=output_path,
        lineage_path=lineage_path,
        invocations=invocations,
    )
