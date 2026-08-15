"""Observation query boundary used by Flow-owned ModelWindow instances."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from vqapr.data import scan
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.resolution import resolve_fields
from vqapr.data.sources import SourceSpec
from vqapr.domain.rows import normalize_rows
from vqapr.domain.timestamps import require_tz_aware


class DatasetCatalog(Protocol):
    def dataset(self, raw_dataset_id: str): ...

    def source(self, raw_source_id: str) -> SourceSpec: ...


class DuckDbObservationStore:
    """Resolve workspace declarations and execute bounded physical queries through scan.py."""

    __slots__ = ("__catalog",)

    def __init__(self, catalog: DatasetCatalog) -> None:
        self.__catalog = catalog

    def query(
        self,
        requirement: DataRequirement,
        *,
        evaluation_time: datetime,
        instruments: Sequence[str],
    ):
        from vqapr.data.windows import AccessRecord, ObservationBatch

        require_tz_aware(evaluation_time, name="evaluation_time")
        registration = self.__catalog.dataset(str(requirement.dataset_id))
        source = self.__catalog.source(str(registration.source))
        fields = resolve_fields(registration, requirement)
        lower_bound = None
        rows = None
        if isinstance(requirement.lookback, RowsLookback):
            rows = requirement.lookback.rows
        elif isinstance(requirement.lookback, CalendarLookback):
            lower_bound = requirement.lookback.lower_bound(evaluation_time)
        else:  # pragma: no cover - DataRequirement construction closes this union
            raise TypeError("unsupported lookback")
        raw_rows = scan.observation_rows(
            source,
            instrument_field=registration.instrument_field,
            available_at_field=registration.available_at,
            key_fields=registration.key_fields,
            fields=fields,
            instruments=instruments,
            evaluation_time=evaluation_time,
            rows=rows,
            lower_bound=lower_bound,
        )
        normalized = normalize_rows(raw_rows)
        actual = {
            instrument: {field: 0 for field in requirement.fields} for instrument in instruments
        }
        max_available_at: datetime | None = None
        for row in normalized:
            instrument = str(row["instrument"])
            for field in requirement.fields:
                if row[field] is not None:
                    actual[instrument][field] += 1
            available_at = row["available_at"]
            if not isinstance(available_at, datetime):
                raise TypeError("registered available_at values must be datetimes")
            if max_available_at is None or available_at > max_available_at:
                max_available_at = available_at
        access = AccessRecord(
            consumer_id=requirement.consumer_id,
            dataset_id=requirement.dataset_id,
            fields=requirement.fields,
            lookback=requirement.lookback,
            evaluation_time=evaluation_time,
            instruments=tuple(instruments),
            lower_bound=lower_bound,
            actual_rows=actual,
            max_available_at=max_available_at,
        )
        return ObservationBatch(normalized, access)
