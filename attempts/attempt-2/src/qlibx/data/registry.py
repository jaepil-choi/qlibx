"""Append-only logical dataset registry."""

import hashlib
import json
import os
from contextlib import suppress
from pathlib import Path

import pandas as pd

from qlibx.data.contracts import (
    CURRENT_QUERY_SNAPSHOT_LAYOUT_VERSION,
    AvailableAtField,
    DatasetRegistration,
    DatasetReindexItem,
    DatasetReindexResult,
    RegisteredDataset,
    RegistrationEvidence,
    SourceFormat,
)
from qlibx.data.snapshot import build_query_snapshot
from qlibx.data.timestamps import TimestampNormalizationError, normalize_timestamps
from qlibx.errors import CommitStatus, OperationError, OperationOutcome, OutcomeStatus


def stable_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def failure(
    registration: DatasetRegistration,
    invocation_id: str,
    stage: str,
    code: str,
    *,
    requirement_id: str | None = None,
    context: dict[str, object] | None = None,
    retry: tuple[str, ...] = (),
) -> OperationOutcome:
    identity = stable_hash(f"{invocation_id}:{stage}:{code}".encode())[:24]
    error = OperationError(
        operation="dataset.register",
        stage_path=f"dataset.register.{stage}",
        error_code=code,
        requirement_id=requirement_id,
        context=context or {},
        commit_status=CommitStatus.NONE,
        retry_preconditions=retry,
        idempotency_identity=invocation_id,
        error_id=f"error-{identity}",
    )
    return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))


def reindex_failure(
    invocation_id: str,
    stage: str,
    code: str,
    *,
    context: dict[str, object] | None = None,
    retry: tuple[str, ...] = (),
) -> OperationOutcome[DatasetReindexResult]:
    identity = stable_hash(f"{invocation_id}:{stage}:{code}".encode())[:24]
    return OperationOutcome(
        status=OutcomeStatus.FAILED,
        errors=(
            OperationError(
                operation="dataset.reindex",
                stage_path=f"dataset.reindex.{stage}",
                error_code=code,
                context=context or {},
                commit_status=CommitStatus.NONE,
                retry_preconditions=retry,
                idempotency_identity=invocation_id,
                error_id=f"error-{identity}",
            ),
        ),
    )


class RegistrySnapshot:
    """Immutable collection used by requirement resolution."""

    def __init__(self, datasets: tuple[RegisteredDataset, ...]) -> None:
        self._datasets = datasets

    @property
    def datasets(self) -> tuple[RegisteredDataset, ...]:
        return self._datasets

    def get(self, dataset_id: str) -> RegisteredDataset | None:
        return next((item for item in self._datasets if item.dataset_id == dataset_id), None)


class DatasetRegistry:
    """Validate registrations fully before making them visible."""

    def __init__(self, project_root: Path, registry_dir: Path) -> None:
        self._project_root = project_root.resolve()
        self._registry_dir = registry_dir.resolve()

    def register(self, registration: DatasetRegistration) -> OperationOutcome:
        source = Path(registration.source)
        if not source.is_absolute():
            source = self._project_root / source
        source = source.resolve()
        invocation_seed = registration.model_dump_json().encode()
        invocation_id = f"invocation-{stable_hash(invocation_seed)[:24]}"

        if not source.is_file():
            return failure(
                registration,
                invocation_id,
                "source",
                "SOURCE_NOT_FOUND",
                context={"source": str(source)},
                retry=("provide an existing CSV or Parquet source",),
            )

        try:
            frame = self._read(source, registration)
        except Exception as exc:
            return failure(
                registration,
                invocation_id,
                "source_read",
                "SOURCE_READ_FAILED",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                retry=("provide a readable source matching source_format",),
            )

        required_fields = set(registration.logical_key)
        required_fields.add(registration.instrument_field)
        if registration.observation_time_field is not None:
            required_fields.add(registration.observation_time_field)
        required_fields.update(registration.semantic_bindings.values())
        if isinstance(registration.available_at, AvailableAtField):
            time_field = registration.available_at.field
        else:
            time_field = registration.available_at.source_field
        required_fields.add(time_field)
        missing = sorted(required_fields - set(frame.columns))
        if missing:
            return failure(
                registration,
                invocation_id,
                "schema",
                "BOUND_FIELD_MISSING",
                requirement_id="dataset.minimal_schema",
                context={"missing_fields": missing[:20], "columns": list(frame.columns)[:20]},
                retry=("bind fields that exist in the physical source",),
            )

        key_null_count = int(frame[list(registration.logical_key)].isna().any(axis=1).sum())
        if key_null_count:
            return failure(
                registration,
                invocation_id,
                "key_null",
                "LOGICAL_KEY_NULL",
                requirement_id="dataset.logical_key",
                context={"null_rows": key_null_count},
                retry=("remove null keys or choose the correct logical key",),
            )
        duplicates = int(frame.duplicated(subset=list(registration.logical_key)).sum())
        if duplicates:
            return failure(
                registration,
                invocation_id,
                "key_uniqueness",
                "LOGICAL_KEY_DUPLICATE",
                requirement_id="dataset.logical_key",
                context={"duplicate_rows": duplicates},
                retry=("add the missing event or sequence axis, or correct duplicate rows",),
            )

        try:
            available_at = normalize_timestamps(
                frame[time_field],
                field=time_field,
                source_timezone=registration.source_timezone,
            )
            normalized_fields = [available_at]
            if (
                registration.observation_time_field is not None
                and registration.observation_time_field != time_field
            ):
                normalized_fields.append(
                    normalize_timestamps(
                        frame[registration.observation_time_field],
                        field=registration.observation_time_field,
                        source_timezone=registration.source_timezone,
                    )
                )
        except TimestampNormalizationError as exc:
            if exc.code == "TIMESTAMP_VALUES_UNPARSEABLE":
                failed_field = str(exc.context["field"])
                is_availability = failed_field == time_field
                return failure(
                    registration,
                    invocation_id,
                    "available_at" if is_availability else "observation_time",
                    exc.code,
                    requirement_id=(
                        "dataset.available_at" if is_availability else "dataset.observation_time"
                    ),
                    context=exc.context,
                    retry=("replace non-null values that cannot be parsed as timestamps",),
                )
            retry = {
                "TIMESTAMP_TIMEZONE_UNDECLARED": (
                    "declare source_timezone for the naive source, or provide "
                    "offset-qualified timestamps",
                ),
                "TIMESTAMP_LOCALIZATION_FAILED": (
                    "provide offset-qualified timestamps for the ambiguous or mixed local times",
                ),
            }.get(
                exc.code,
                ("provide timestamps with explicit, parseable instant semantics",),
            )
            return failure(
                registration,
                invocation_id,
                "timestamp_timezone",
                exc.code,
                context=exc.context,
                retry=retry,
            )
        parsed_time = available_at.utc
        invalid_time = int(parsed_time.isna().sum())
        if invalid_time:
            return failure(
                registration,
                invocation_id,
                "available_at",
                "AVAILABLE_AT_INVALID",
                requirement_id="dataset.available_at",
                context={"invalid_rows": invalid_time, "field": time_field},
                retry=("bind a parseable availability field or confirm a valid delay rule",),
            )
        if registration.source_timezone is not None and not any(
            item.was_naive for item in normalized_fields
        ):
            return failure(
                registration,
                invocation_id,
                "timestamp_timezone",
                "TIMESTAMP_TIMEZONE_UNUSED",
                context={"source_timezone": registration.source_timezone},
                retry=("remove source_timezone; the source timestamps already carry an offset",),
            )
        if not isinstance(registration.available_at, AvailableAtField):
            parsed_time = parsed_time + pd.to_timedelta(
                registration.available_at.delay_seconds,
                unit="s",
            )

        physical_fingerprint = file_hash(source)
        schema_payload = json.dumps(
            [(str(column), str(dtype)) for column, dtype in frame.dtypes.items()],
            separators=(",", ":"),
        ).encode()
        schema_fingerprint = stable_hash(schema_payload)
        identity_payload = (
            registration.model_dump_json() + physical_fingerprint + schema_fingerprint
        ).encode()
        registration_identity = stable_hash(identity_payload)
        try:
            built_snapshot = build_query_snapshot(
                registration=registration,
                frame=frame,
                available_at=parsed_time,
                snapshot_dir=self._registry_dir.parent / "query-snapshots",
            )
        except Exception as exc:
            return failure(
                registration,
                invocation_id,
                "query_snapshot",
                "DATASET_QUERY_SNAPSHOT_PUBLICATION_FAILED",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                retry=("make the project data directory writable and retry registration",),
            )
        registered = RegisteredDataset(
            registration_schema_version=2,
            dataset_id=registration.dataset_id,
            registration_identity=registration_identity,
            physical_fingerprint=physical_fingerprint,
            schema_fingerprint=schema_fingerprint,
            source=str(source),
            source_format=registration.source_format,
            instrument_field=registration.instrument_field,
            observation_time_field=registration.observation_time_field,
            source_timezone=registration.source_timezone,
            available_at=registration.available_at,
            logical_key=registration.logical_key,
            bindings=built_snapshot.bindings,
            source_bindings=registration.semantic_bindings,
            semantic_category=registration.semantic_category,
            source_provenance=registration.source_provenance,
            query_snapshot=built_snapshot.snapshot,
            evidence=RegistrationEvidence(
                row_count=len(frame),
                columns=tuple(str(column) for column in frame.columns),
                logical_key_unique=True,
                logical_key_null_count=0,
                available_at_min=parsed_time.min().isoformat() if len(parsed_time) else None,
                available_at_max=parsed_time.max().isoformat() if len(parsed_time) else None,
                localized_source_timezone=(
                    registration.source_timezone
                    if any(item.was_naive for item in normalized_fields)
                    else None
                ),
            ),
        )
        return self._publish(registered, registration, invocation_id)

    def reindex(
        self,
        dataset_ids: tuple[str, ...] | None = None,
    ) -> OperationOutcome[DatasetReindexResult]:
        snapshot = self.snapshot()
        selected_ids = (
            tuple(sorted(dataset_ids))
            if dataset_ids is not None
            else tuple(item.dataset_id for item in snapshot.datasets)
        )
        invocation_id = f"dataset-reindex:{stable_hash(':'.join(selected_ids).encode())[:24]}"
        selected: list[RegisteredDataset] = []
        for dataset_id in selected_ids:
            dataset = snapshot.get(dataset_id)
            if dataset is None:
                return reindex_failure(
                    invocation_id,
                    "selection",
                    "DATASET_NOT_REGISTERED",
                    context={"dataset_id": dataset_id},
                    retry=("select only registered dataset IDs",),
                )
            source = Path(dataset.source).resolve()
            if not source.is_file() or file_hash(source) != dataset.physical_fingerprint:
                return reindex_failure(
                    invocation_id,
                    "source",
                    "DATASET_SOURCE_DRIFT",
                    context={
                        "dataset_id": dataset.dataset_id,
                        "registration_identity": dataset.registration_identity,
                    },
                    retry=("restore the exact registered source before reindexing",),
                )
            selected.append(dataset)

        pending: list[tuple[RegisteredDataset, RegisteredDataset, bool]] = []
        for dataset in selected:
            existing = dataset.query_snapshot
            if existing is not None:
                path = Path(existing.path).resolve()
                if not path.is_file() or file_hash(path) != existing.fingerprint:
                    return reindex_failure(
                        invocation_id,
                        "snapshot",
                        "DATASET_QUERY_SNAPSHOT_DRIFT",
                        context={"dataset_id": dataset.dataset_id},
                        retry=("restore the registered query snapshot",),
                    )
                if (
                    dataset.registration_schema_version == 2
                    and existing.layout_version == CURRENT_QUERY_SNAPSHOT_LAYOUT_VERSION
                ):
                    pending.append((dataset, dataset, False))
                    continue
            semantic_bindings = dataset.source_bindings or {
                role: field
                for role, field in dataset.bindings.items()
                if role not in {"instrument", "available_at"}
            }
            registration = DatasetRegistration(
                dataset_id=dataset.dataset_id,
                source=dataset.source,
                source_format=dataset.source_format,
                instrument_field=dataset.instrument_field,
                observation_time_field=dataset.observation_time_field,
                source_timezone=dataset.source_timezone,
                available_at=dataset.available_at,
                logical_key=dataset.logical_key,
                semantic_bindings=semantic_bindings,
                semantic_category=dataset.semantic_category,
                source_provenance=dataset.source_provenance,
            )
            try:
                frame = self._read(Path(dataset.source), registration)
                time_field = (
                    registration.available_at.field
                    if isinstance(registration.available_at, AvailableAtField)
                    else registration.available_at.source_field
                )
                available_at = normalize_timestamps(
                    frame[time_field],
                    field=time_field,
                    source_timezone=registration.source_timezone,
                ).utc
                if not isinstance(registration.available_at, AvailableAtField):
                    available_at = available_at + pd.to_timedelta(
                        registration.available_at.delay_seconds,
                        unit="s",
                    )
                built = build_query_snapshot(
                    registration=registration,
                    frame=frame,
                    available_at=available_at,
                    snapshot_dir=self._registry_dir.parent / "query-snapshots",
                )
            except Exception as exc:
                return reindex_failure(
                    invocation_id,
                    "build",
                    "DATASET_REINDEX_FAILED",
                    context={
                        "dataset_id": dataset.dataset_id,
                        "exception": type(exc).__name__,
                        "message": str(exc)[:500],
                    },
                    retry=("repair the registered source contract and retry reindex",),
                )
            upgraded = dataset.model_copy(
                update={
                    "registration_schema_version": 2,
                    "bindings": built.bindings,
                    "source_bindings": semantic_bindings,
                    "query_snapshot": built.snapshot,
                }
            )
            pending.append((dataset, upgraded, True))

        items: list[DatasetReindexItem] = []
        for original, upgraded, changed in pending:
            if changed:
                destination = self._registry_dir / f"{original.dataset_id}.json"
                temporary = self._registry_dir / f".{original.dataset_id}.{os.getpid()}.reindex.tmp"
                temporary.write_text(
                    upgraded.model_dump_json(indent=2),
                    encoding="utf-8",
                    newline="\n",
                )
                os.replace(temporary, destination)
            assert upgraded.query_snapshot is not None
            items.append(
                DatasetReindexItem(
                    dataset_id=upgraded.dataset_id,
                    registration_identity=upgraded.registration_identity,
                    snapshot_fingerprint=upgraded.query_snapshot.fingerprint,
                    changed=changed,
                )
            )
        return OperationOutcome(
            status=OutcomeStatus.COMPLETE,
            result=DatasetReindexResult(items=tuple(items)),
        )

    def snapshot(self) -> RegistrySnapshot:
        if not self._registry_dir.is_dir():
            return RegistrySnapshot(())
        datasets = tuple(
            RegisteredDataset.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self._registry_dir.glob("*.json"))
        )
        return RegistrySnapshot(datasets)

    @staticmethod
    def _read(source: Path, registration: DatasetRegistration) -> pd.DataFrame:
        if registration.source_format is SourceFormat.CSV:
            return pd.read_csv(source, dtype={registration.instrument_field: "string"})
        return pd.read_parquet(source)

    def _publish(
        self,
        registered: RegisteredDataset,
        registration: DatasetRegistration,
        invocation_id: str,
    ) -> OperationOutcome:
        destination = self._registry_dir / f"{registered.dataset_id}.json"
        if destination.exists():
            current = RegisteredDataset.model_validate_json(destination.read_text(encoding="utf-8"))
            if current.registration_identity == registered.registration_identity:
                return OperationOutcome(status=OutcomeStatus.COMPLETE, result=current)
            return failure(
                registration,
                invocation_id,
                "identity_conflict",
                "REGISTRATION_IDENTITY_CONFLICT",
                context={"dataset_id": registered.dataset_id},
                retry=("choose a new dataset_id or retain the existing immutable registration",),
            )

        self._registry_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._registry_dir / f".{registered.dataset_id}.{os.getpid()}.tmp"
        temporary.write_text(registered.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            return self._publish(registered, registration, invocation_id)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            return failure(
                registration,
                invocation_id,
                "publication",
                "REGISTRY_PUBLICATION_FAILED",
                context={"exception": type(exc).__name__, "message": str(exc)[:500]},
                retry=("use a local filesystem that supports atomic hard-link publication",),
            )
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        return OperationOutcome(status=OutcomeStatus.COMPLETE, result=registered)
