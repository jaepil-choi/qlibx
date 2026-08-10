"""Registration-time normalized Parquet query snapshots."""

import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from qlibx.data.contracts import DatasetQuerySnapshot, DatasetRegistration
from qlibx.data.timestamps import normalize_timestamps


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class BuiltQuerySnapshot:
    snapshot: DatasetQuerySnapshot
    bindings: dict[str, str]


def build_query_snapshot(
    *,
    registration: DatasetRegistration,
    frame: pd.DataFrame,
    available_at: pd.Series,
    snapshot_dir: Path,
) -> BuiltQuerySnapshot:
    """Normalize only registered query columns and publish a content-addressed Parquet."""

    time_field = (
        registration.available_at.field
        if registration.available_at.kind == "field"
        else registration.available_at.source_field
    )
    observation_time = (
        normalize_timestamps(
            frame[registration.observation_time_field],
            field=registration.observation_time_field,
            source_timezone=registration.source_timezone,
        ).utc
        if registration.observation_time_field is not None
        else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    )
    instrument = frame[registration.instrument_field].astype("string")
    canonical_by_source = {
        registration.instrument_field: "instrument",
        time_field: "available_at",
        **(
            {registration.observation_time_field: "observation_time"}
            if registration.observation_time_field is not None
            else {}
        ),
    }
    snapshot_bindings: dict[str, str] = {
        "instrument": "instrument",
        "available_at": "available_at",
    }
    normalized: dict[str, pd.Series] = {
        "instrument": instrument,
        "available_at": available_at,
        "observation_time": observation_time,
    }
    used = set(normalized)
    source_column_map: dict[str, str] = dict(canonical_by_source)
    for index, source_field in enumerate(sorted(set(registration.semantic_bindings.values()))):
        column = source_column_map.get(source_field)
        if column is None:
            candidate = source_field
            if candidate in used or candidate.startswith("__key_"):
                candidate = f"__field_{index:03d}"
            column = candidate
            source_column_map[source_field] = column
            normalized[column] = frame[source_field]
            used.add(column)
    for role, source_field in registration.semantic_bindings.items():
        snapshot_bindings[role] = source_column_map[source_field]

    logical_order_columns: list[str] = []
    for index, source_field in enumerate(registration.logical_key):
        column = f"__key_{index:03d}"
        logical_order_columns.append(column)
        canonical = canonical_by_source.get(source_field)
        if canonical == "instrument":
            normalized[column] = instrument
        elif canonical == "available_at":
            normalized[column] = available_at
        elif canonical == "observation_time":
            normalized[column] = observation_time
        else:
            normalized[column] = frame[source_field]

    normalized_frame = pd.DataFrame(normalized)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    temporary = snapshot_dir / f".query-snapshot.{os.getpid()}.tmp.parquet"
    normalized_frame.to_parquet(temporary, index=False)
    fingerprint = file_hash(temporary)
    destination = snapshot_dir / f"{fingerprint}.parquet"
    try:
        os.link(temporary, destination)
    except FileExistsError:
        if file_hash(destination) != fingerprint:
            raise RuntimeError("content-addressed query snapshot is corrupt") from None
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
    return BuiltQuerySnapshot(
        snapshot=DatasetQuerySnapshot(
            path=str(destination.resolve()),
            fingerprint=fingerprint,
            row_count=len(normalized_frame),
            columns=tuple(normalized_frame.columns),
            logical_order_columns=tuple(logical_order_columns),
        ),
        bindings=snapshot_bindings,
    )
