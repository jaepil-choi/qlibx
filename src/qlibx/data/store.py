"""Private observation access used only by scoped views."""

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from qlibx.data.contracts import AvailableAtField, RegisteredDataset, SourceFormat
from qlibx.data.registry import file_hash
from qlibx.data.timestamps import TimestampNormalizationError, normalize_timestamps


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
        session_date: date | None = None,
        observation_at: datetime | None = None,
    ) -> pd.DataFrame:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("view as_of must be timezone-aware")
        cutoff = as_of.astimezone(UTC)
        source = Path(dataset.source)
        if not source.is_file() or file_hash(source) != dataset.physical_fingerprint:
            raise DataSnapshotError(
                f"physical source no longer matches registration {dataset.registration_identity}"
            )
        if isinstance(dataset.available_at, AvailableAtField):
            time_field = dataset.available_at.field
        else:
            time_field = dataset.available_at.source_field
        selected_columns = {
            dataset.instrument_field,
            time_field,
            *(() if field == "__available_at__" else (field,)),
            *(
                ()
                if dataset.observation_time_field is None
                else (dataset.observation_time_field,)
            ),
        }
        if dataset.source_format is SourceFormat.CSV:
            frame = pd.read_csv(
                source,
                usecols=sorted(selected_columns),
                dtype={dataset.instrument_field: "string"},
            )
        else:
            frame = pd.read_parquet(source, columns=sorted(selected_columns))

        try:
            available_at = normalize_timestamps(
                frame[time_field],
                field=time_field,
                source_timezone=dataset.source_timezone,
            ).utc
            observation_time = (
                normalize_timestamps(
                    frame[dataset.observation_time_field],
                    field=dataset.observation_time_field,
                    source_timezone=dataset.source_timezone,
                ).utc
                if dataset.observation_time_field is not None
                else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
            )
        except TimestampNormalizationError as exc:
            raise DataSnapshotError(
                f"registered timestamp contract is no longer readable ({exc.code}); "
                "re-register the dataset with an explicit source_timezone"
            ) from exc
        if not isinstance(dataset.available_at, AvailableAtField):
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
                "observation_time": observation_time,
                "value": values,
            }
        )
        visible = visible.loc[visible["available_at"] <= cutoff]
        if session_date is not None:
            if dataset.observation_time_field is None:
                raise DataSnapshotError(
                    "session query requires an observation_time_field registration"
                )
            visible = visible.loc[visible["observation_time"].dt.date == session_date]
        if observation_at is not None:
            if dataset.observation_time_field is None:
                raise DataSnapshotError(
                    "point query requires an observation_time_field registration"
                )
            if observation_at.tzinfo is None or observation_at.utcoffset() is None:
                raise ValueError("observation_at must be timezone-aware")
            selected_observation = observation_at.astimezone(UTC)
            visible = visible.loc[
                visible["observation_time"] == selected_observation
            ]
        return visible.sort_values(
            ["available_at", "observation_time", "instrument"],
            kind="mergesort",
        ).reset_index(drop=True)
