"""Observation query boundary used by Flow-owned ModelWindow instances."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from vqapr.data import scan
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.rows import Rows
from vqapr.domain.timestamps import require_tz_aware


class DatasetCatalog(Protocol):
    def dataset(self, raw_dataset_id: str): ...

    def dataset_for_field(self, field_id: str): ...

    def source(self, raw_source_id: str) -> SourceSpec: ...


def _physical_digest(path: Path) -> str:
    files = (path,) if path.is_file() else tuple(sorted(path.glob("**/*.parquet")))
    if not files:
        raise FileNotFoundError(f"source has no readable parquet bytes: {path}")
    digest = hashlib.sha256()
    for file_path in files:
        with file_path.open("rb") as stream:
            hashlib.file_digest(stream, lambda: digest)
    return digest.hexdigest()


class DuckDbObservationStore:
    """Resolve workspace declarations and execute bounded physical queries through scan.py."""

    __slots__ = ("__catalog", "__digests", "__session")

    def __init__(self, catalog: DatasetCatalog, *, session: scan.ScanSession | None = None) -> None:
        self.__catalog = catalog
        # None keeps the connect-per-query behaviour, so every existing caller and test is
        # unaffected. public.run() passes a run-lifetime session.
        self.__session = session
        # One store instance lives for exactly one run, and a run's sources are frozen for its
        # whole duration. SimulationFlow._actual_source_refs already refuses a callback that
        # observes two digests for one source, so caching per instance does not weaken that
        # contract -- it makes violating it impossible instead of merely detected.
        self.__digests: dict[Path, str] = {}

    def _digest(self, path: Path) -> str:
        cached = self.__digests.get(path)
        if cached is None:
            cached = self.__digests[path] = _physical_digest(path)
        return cached

    def query(
        self,
        requirement: DataRequirement,
        *,
        evaluation_time: datetime,
        instruments: Sequence[str],
        consumer_id: str,
    ):
        from vqapr.data.windows import AccessRecord, ObservationBatch

        require_tz_aware(evaluation_time, name="evaluation_time")
        # The requirement names a field; which dataset that is comes from the registration that
        # declared it, not from the requirement (`docs/issues/049`).
        registration = self.__catalog.dataset_for_field(requirement.field_id)
        keyed_by_instrument = registration.instrument_field is not None
        source = self.__catalog.source(str(registration.source))
        source_digest = self._digest(source.path)
        fields = {requirement.field_id: registration.fields[requirement.field_id]}
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
            aggregated=registration.aggregated,
            instruments=instruments,
            evaluation_time=evaluation_time,
            rows=rows,
            lower_bound=lower_bound,
            session=self.__session,
        )
        # The read path validates nothing. What `observation_rows` just handed back was built
        # from this package's own registered parquet, three statements ago, out of one cursor
        # description -- so `normalize_rows` used to ask every cell a question registration had
        # already settled, and asked the same column names once per row on top of that
        # (`docs/issues/044`). Registration now refuses a non-finite, naive or non-portable
        # column outright (`datasets.check_schema`, `datasets.check_values`), which is where
        # that question is cheap: once per column instead of once per cell. Data that only turns
        # out to be wrong at runtime is not chased here; it fails where it is used.
        normalized: Rows = raw_rows  # type: ignore[assignment]
        # One dict lookup per row instead of one per row and field, and `dict.fromkeys` instead of
        # a comprehension per instrument. The counts and the failure on an unknown instrument are
        # what they were.
        #
        # A dataset with no instrument axis has no per-instrument counts to keep and no declared
        # instruments to keep them for (`docs/issues/038`). Its rows carry no `instrument`, so the
        # record says so with two empty values rather than inventing a name to file them under.
        declared_fields = (requirement.field_id,)
        actual: dict[str, dict[str, int]] = {}
        if keyed_by_instrument:
            actual = {instrument: dict.fromkeys(declared_fields, 0) for instrument in instruments}
        max_available_at: datetime | None = None
        for row in normalized:
            if keyed_by_instrument:
                counts = actual[str(row["instrument"])]
                for field in declared_fields:
                    if row[field] is not None:
                        counts[field] += 1
            available_at = row["available_at"]
            if not isinstance(available_at, datetime):
                raise TypeError("registered available_at values must be datetimes")
            if max_available_at is None or available_at > max_available_at:
                max_available_at = available_at
        access = AccessRecord(
            # Stamped, not declared. The component reading is the consumer, and the framework is
            # the only one that knows which component is running.
            consumer_id=consumer_id,
            dataset_id=registration.dataset_id,
            source_id=str(source.source_id),
            source_digest=source_digest,
            fields=declared_fields,
            lookback=requirement.lookback,
            evaluation_time=evaluation_time,
            instruments=tuple(instruments) if keyed_by_instrument else (),
            lower_bound=lower_bound,
            actual_rows=actual,
            max_available_at=max_available_at,
        )
        # The public constructor validates every cell, which costs about as much as the query
        # that produced them, so take the same trusted door `ModelWindow.snapshot` already uses.
        return ObservationBatch._trusted(normalized, access)
