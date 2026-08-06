"""Private observation access used only by scoped views."""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from qlibx.data.contracts import AvailableAtField, RegisteredDataset, SourceFormat
from qlibx.data.registry import file_hash


class DataSnapshotError(RuntimeError):
    """Raised when registered physical data no longer matches its frozen identity."""


class ObservationStore:
    """Read registered observations with an unavoidable availability predicate."""

    def query(
        self,
        dataset: RegisteredDataset,
        *,
        field: str,
        as_of: datetime,
    ) -> pd.DataFrame:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("view as_of must be timezone-aware")
        cutoff = as_of.astimezone(timezone.utc)
        source = Path(dataset.source)
        if not source.is_file() or file_hash(source) != dataset.physical_fingerprint:
            raise DataSnapshotError(
                f"physical source no longer matches registration {dataset.registration_identity}"
            )
        if dataset.source_format is SourceFormat.CSV:
            frame = pd.read_csv(source, dtype={dataset.instrument_field: "string"})
        else:
            frame = pd.read_parquet(source)

        if isinstance(dataset.available_at, AvailableAtField):
            time_field = dataset.available_at.field
            available_at = pd.to_datetime(frame[time_field], errors="raise", utc=True)
        else:
            time_field = dataset.available_at.source_field
            available_at = pd.to_datetime(frame[time_field], errors="raise", utc=True)
            available_at = available_at + pd.to_timedelta(
                dataset.available_at.delay_seconds,
                unit="s",
            )
        if field != "__available_at__" and field not in frame.columns:
            raise DataSnapshotError(
                f"registered field {field!r} is absent from the physical source"
            )
        values = available_at if field == "__available_at__" else frame[field]
        visible = pd.DataFrame(
            {
                "instrument": frame[dataset.instrument_field].astype("string"),
                "available_at": available_at,
                "value": values,
            }
        )
        visible = visible.loc[visible["available_at"] <= cutoff]
        return visible.sort_values(
            ["available_at", "instrument"],
            kind="mergesort",
        ).reset_index(drop=True)
