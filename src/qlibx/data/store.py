"""Private bounded observation access used only by scoped views."""

import calendar
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from qlibx.data.contracts import CalendarLookback, Lookback, RegisteredDataset, RowsLookback
from qlibx.data.registry import file_hash


class DataSnapshotError(RuntimeError):
    """Raised when registered source or query-snapshot authority is unavailable."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ObservationStore:
    """Query immutable normalized Parquet with mandatory PIT and bounded history."""

    def __init__(self) -> None:
        self._frozen_depth = 0
        self._frozen_verified: set[tuple[str, str, str]] = set()

    @contextmanager
    def frozen(self) -> Iterator[None]:
        """Verify each physical source and snapshot once in one invocation scope."""

        outermost = self._frozen_depth == 0
        if outermost:
            self._frozen_verified.clear()
        self._frozen_depth += 1
        try:
            yield
        finally:
            self._frozen_depth -= 1
            if outermost:
                self._frozen_verified.clear()

    def query(
        self,
        dataset: RegisteredDataset,
        *,
        field: str,
        as_of: datetime,
        session_date: date | None = None,
        session_timezone: str | None = None,
        observation_at: datetime | None = None,
        lookback: Lookback | None = None,
        instruments: tuple[str, ...] | None = None,
        latest: bool = False,
    ) -> pd.DataFrame:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("view as_of must be timezone-aware")
        if session_date is not None and session_timezone is None:
            raise ValueError("session query requires an explicit session_timezone")
        if observation_at is not None and (
            observation_at.tzinfo is None or observation_at.utcoffset() is None
        ):
            raise ValueError("observation_at must be timezone-aware")
        bounded_point = session_date is not None or observation_at is not None or latest
        if lookback is None and not bounded_point:
            raise DataSnapshotError(
                "DATASET_LOOKBACK_REQUIRED",
                "historical reads require a declared rows or calendar lookback",
            )
        if sum(value is not None for value in (session_date, observation_at)) + int(latest) > 1:
            raise ValueError("session, point, and latest query modes are mutually exclusive")

        snapshot = dataset.query_snapshot
        if dataset.registration_schema_version != 2 or snapshot is None:
            raise DataSnapshotError(
                "DATASET_QUERY_SNAPSHOT_REQUIRED",
                f"dataset {dataset.dataset_id!r} requires project.reindex_datasets()",
            )
        source = Path(dataset.source).resolve()
        snapshot_path = Path(snapshot.path).resolve()
        self._verify(
            kind="source",
            path=source,
            expected=dataset.physical_fingerprint,
            code="DATASET_SOURCE_DRIFT",
            message=(
                f"physical source no longer matches registration {dataset.registration_identity}"
            ),
        )
        self._verify(
            kind="snapshot",
            path=snapshot_path,
            expected=snapshot.fingerprint,
            code="DATASET_QUERY_SNAPSHOT_DRIFT",
            message=f"query snapshot no longer matches dataset {dataset.dataset_id!r}",
        )
        selected_field = "available_at" if field == "__available_at__" else field
        if selected_field not in snapshot.columns:
            raise DataSnapshotError(
                "DATASET_BOUND_FIELD_MISSING",
                f"registered field {field!r} is absent from the query snapshot",
            )

        cutoff = as_of.astimezone(UTC)
        predicates = ["available_at <= ?"]
        parameters: list[object] = [cutoff]
        if instruments is not None:
            canonical = tuple(sorted(set(instruments)))
            if canonical:
                predicates.append(f"instrument IN ({','.join('?' for _ in canonical)})")
                parameters.extend(canonical)
            else:
                predicates.append("FALSE")
        if session_date is not None:
            if dataset.observation_time_field is None:
                raise DataSnapshotError(
                    "DATASET_OBSERVATION_TIME_REQUIRED",
                    "session query requires an observation_time_field registration",
                )
            start = datetime.combine(
                session_date,
                time.min,
                tzinfo=ZoneInfo(session_timezone),
            ).astimezone(UTC)
            end = start + timedelta(days=1)
            predicates.extend(("observation_time >= ?", "observation_time < ?"))
            parameters.extend((start, end))
        if observation_at is not None:
            if dataset.observation_time_field is None:
                raise DataSnapshotError(
                    "DATASET_OBSERVATION_TIME_REQUIRED",
                    "point query requires an observation_time_field registration",
                )
            predicates.append("observation_time = ?")
            parameters.append(observation_at.astimezone(UTC))
        if isinstance(lookback, CalendarLookback):
            lower = _calendar_lower_bound(as_of, lookback)
            predicates.append("available_at >= ?")
            parameters.append(lower)

        field_sql = _identifier(selected_field)
        ordering = _ordering(snapshot.logical_order_columns)
        where_sql = " AND ".join(predicates)
        source_sql = (
            "SELECT instrument, available_at, observation_time, "
            f"{field_sql} AS value, {ordering} "
            "FROM read_parquet(?) "
            f"WHERE {where_sql}"
        )
        query_parameters: list[object] = [str(snapshot_path), *parameters]
        if isinstance(lookback, RowsLookback):
            sql = (
                "WITH visible AS ("
                + source_sql
                + "), ranked AS (SELECT *, row_number() OVER (PARTITION BY instrument ORDER BY "
                + _descending_order(snapshot.logical_order_columns)
                + ") AS __rank FROM visible) "
                "SELECT instrument, available_at, observation_time, value FROM ranked "
                "WHERE __rank <= ? ORDER BY instrument, available_at, observation_time, " + ordering
            )
            query_parameters.append(lookback.rows)
        elif latest:
            sql = (
                "WITH visible AS ("
                + source_sql
                + "), ranked AS (SELECT *, row_number() OVER (PARTITION BY instrument ORDER BY "
                + _descending_order(snapshot.logical_order_columns)
                + ") AS __rank FROM visible) "
                "SELECT instrument, available_at, observation_time, value FROM ranked "
                "WHERE __rank = 1 ORDER BY instrument"
            )
        else:
            sql = (
                "WITH visible AS ("
                + source_sql
                + ") SELECT instrument, available_at, observation_time, value FROM visible "
                "ORDER BY instrument, available_at, observation_time, " + ordering
            )
        connection = duckdb.connect(database=":memory:")
        try:
            return connection.execute(sql, query_parameters).fetchdf()
        finally:
            connection.close()

    def latest(
        self,
        dataset: RegisteredDataset,
        *,
        field: str,
        as_of: datetime,
        instruments: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        return self.query(
            dataset,
            field=field,
            as_of=as_of,
            instruments=instruments,
            latest=True,
        )

    def _verify(
        self,
        *,
        kind: str,
        path: Path,
        expected: str,
        code: str,
        message: str,
    ) -> None:
        key = (kind, str(path), expected)
        if self._frozen_depth > 0 and key in self._frozen_verified:
            return
        if not path.is_file() or file_hash(path) != expected:
            raise DataSnapshotError(code, message)
        if self._frozen_depth > 0:
            self._frozen_verified.add(key)


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _ordering(columns: tuple[str, ...]) -> str:
    return ", ".join(_identifier(column) for column in columns)


def _descending_order(columns: tuple[str, ...]) -> str:
    return "available_at DESC, observation_time DESC, " + ", ".join(
        f"{_identifier(column)} DESC NULLS LAST" for column in columns
    )


def _calendar_lower_bound(as_of: datetime, lookback: CalendarLookback) -> datetime:
    timezone = ZoneInfo(lookback.timezone)
    local_date = as_of.astimezone(timezone).date()
    total_months = local_date.year * 12 + local_date.month - 1
    total_months -= lookback.years * 12 + lookback.months
    year, zero_based_month = divmod(total_months, 12)
    month = zero_based_month + 1
    day = min(local_date.day, calendar.monthrange(year, month)[1])
    shifted = date(year, month, day) - timedelta(days=lookback.days)
    return datetime.combine(shifted, time.min, tzinfo=timezone).astimezone(UTC)
