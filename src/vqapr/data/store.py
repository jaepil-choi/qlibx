"""Observation query boundary used by Flow-owned ModelWindow instances."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from vqapr.data import scan
from vqapr.data.datasets import Grain, lookback_fits_grain, require_declared
from vqapr.data.lookback import (
    CalendarLookback,
    InstantsLookback,
    Lookback,
    RowsLookback,
)
from vqapr.data.panel import Panel, panel_identity
from vqapr.data.requirements import DataRequirement
from vqapr.data.resolution import resolve_field
from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import DatasetId
from vqapr.domain.values import Rows, normalize_rows, require_tz_aware


class DatasetCatalog(Protocol):
    def dataset(self, raw_dataset_id: str): ...

    def source(self, raw_source_id: str) -> SourceSpec: ...


def physical_digest(path: Path) -> str:
    """The sha256 of a source's parquet bytes: what a registration's id and path stand for.

    Public since record `139`: `run.json` records it per source (testbed A7), so a run says which
    bytes it read and not only which path it was pointed at.
    """
    files = (path,) if path.is_file() else tuple(sorted(path.glob("**/*.parquet")))
    if not files:
        raise FileNotFoundError(f"source has no readable parquet bytes: {path}")
    digest = hashlib.sha256()
    for file_path in files:
        with file_path.open("rb") as stream:
            hashlib.file_digest(stream, lambda: digest)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class AccessRecord:
    consumer_id: str
    dataset_id: DatasetId
    source_id: str
    source_digest: str
    fields: tuple[str, ...]
    lookback: Lookback
    evaluation_time: datetime
    instruments: tuple[str, ...]
    lower_bound: datetime | None
    actual_rows: Mapping[str, Mapping[str, int]]
    max_available_at: datetime | None


@dataclass(frozen=True, slots=True)
class ObservationBatch:
    """What one declared requirement returned, and the record of how it was read.

    This is the only shape a Model ever receives data in, and until 2026-08-30 it was not
    importable from `vqapr.public` and had no docstring -- so an author could read its name in
    `observations()`'s signature and had no way to learn what it holds without opening installed
    source. One journey answered the questions below by registering a throwaway DataModel that
    reported `sorted(rows[0].keys())`, which is a full register-materialize-show cycle spent on one
    type's field names (`docs/issues/031`).

    **`rows` is a flat tuple of dicts, one per (instant, instrument) observation.** Every row
    carries:

    * `available_at` -- a timezone-aware `datetime`, the row's OWN point-in-time stamp rather than
      the window's evaluation time. Rows do not share one instant, so this is what a cross-section
      is built on.
    * `instrument` -- the instrument id, as a string. **Absent** on a dataset registered with no
      `instrument_field`: those rows are not keyed by instrument, the declared instrument list is
      not applied to them, and there is no name to put here (`docs/issues/038`).
    * the field the requirement named, under its own id -- a requirement names one field and a
      lookback, and nothing else (`docs/issues/049`). A value is `None` where the source has no
      value; an `InstantsLookback` also nulls it on rows outside that field's own last-N instants
      (see `InstantsLookback`).

    **A value arrives as the Python type of the field's declared `ColumnType`.** `DOUBLE` is
    `float`, `INTEGER` is `int`, `VARCHAR` is `str`, `BOOLEAN` is `bool`, `TIMESTAMP_TZ` is an
    aware `datetime`, `DATE` a `date`. Nothing here converts: the declaration was compared with
    the file once, at registration (`docs/issues/088`), and a DECIMAL column was refused there, so
    `Decimal` never arrives from a dataset. A model that wants exact arithmetic on a price crosses
    once, through `Decimal(str(value))` -- `Decimal(value)` on a float inherits the binary
    expansion -- which is what the scaffolds emit.

    **Ordering is guaranteed: ascending `available_at`, then the dataset's registered key fields.**
    It is pushed into SQL (`scan.observation_rows`) rather than applied afterwards, so it holds for
    every lookback and every instrument count, and `tests/data/test_observation_batch_shape.py`
    pins it. A dataset whose fields aggregate within an instant orders by `available_at` then
    `instrument` instead, because the key fields were consumed making the group and are not in
    what came out of it. Instruments therefore INTERLEAVE within an instant rather than being
    grouped by name:
    a per-instrument series is built by the reader, and a cross-section is `rows` filtered on one
    `available_at`. `ModelWindow.snapshot` returns the newest cross-section directly.

    `access` is the `AccessRecord` the framework stamps -- source digest, declared fields, the
    lookback, the bound it resolved, per-instrument non-null counts. It is provenance, not data,
    and a Model normally reads only `rows`.
    """

    rows: Rows
    access: AccessRecord

    def __init__(self, rows: object, access: AccessRecord) -> None:
        object.__setattr__(self, "rows", normalize_rows(rows))
        if not isinstance(access, AccessRecord):
            raise TypeError("access must be an AccessRecord")
        object.__setattr__(self, "access", access)

    @classmethod
    def _trusted(cls, rows: Rows, access: AccessRecord) -> ObservationBatch:
        """Build from rows this module already normalized.

        The public constructor validates every cell because it accepts outside input. Rows taken
        from a batch this module produced have passed that check once already, and checking them
        again costs the same as the query that produced them.
        """
        batch = cls.__new__(cls)
        object.__setattr__(batch, "rows", rows)
        object.__setattr__(batch, "access", access)
        return batch


class DuckDbObservationStore:
    """Resolve workspace declarations and execute bounded physical queries through scan.py."""

    __slots__ = ("__catalog", "__digests", "__panels", "__session")

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
        # One panel per (dataset, declared fields, instruments) for the life of this store --
        # which is the life of one run. Two strategies in one run reading one dataset see one
        # object. Keyed by content identity, so the same bytes build the same key.
        self.__panels: dict[str, Panel] = {}

    def _grid_bound(
        self, source: SourceSpec, available_at_field: str, evaluation_time: datetime, rows: int
    ) -> datetime:
        """The instant `rows` table rows back from the evaluation time.

        When the table has fewer instants at or before the cutoff than were asked for, the bound
        is its first instant: the window is then everything up to the cutoff, which is the honest
        answer to "the last 313 rows" of a 200-row table. An empty table bounds at the cutoff
        itself, which admits nothing, which is what it holds.
        """
        grid = self._instant_grid(source, available_at_field)
        if not grid:
            return evaluation_time
        try:
            cut = bisect_right(grid, evaluation_time)  # type: ignore[type-var]
        except TypeError:
            return grid[0]  # type: ignore[return-value]
        if cut <= rows:
            return grid[0]  # type: ignore[return-value]
        return grid[cut - rows]  # type: ignore[return-value]

    def panel_window(
        self,
        requirements: Sequence[DataRequirement],
        field: str,
        *,
        evaluation_time: datetime,
        instruments: Sequence[str],
        consumer_id: str,
    ):
        """One field of a panel-grain alias, as a slice of the panel built once for the run.

        `requirements` are the alias's -- one dataset, one lookback, one field each -- and the
        panel is built for all of them in one scan the first time any of them is read, then
        sliced by arithmetic on every read after. The access record is the same fact a row read
        records: what was read, how far back, and how many values each name actually had.
        """
        require_tz_aware(evaluation_time, name="evaluation_time")
        declared = tuple(requirements)
        if not declared:
            raise ValueError("a read requires at least one DataRequirement")
        first = declared[0]
        if any(item.dataset_id != first.dataset_id for item in declared):
            raise ValueError("one read serves one dataset; split requirements by dataset_id")
        if any(item.lookback != first.lookback for item in declared):
            raise ValueError("one read serves one lookback; split requirements by lookback")
        fields = tuple(item.field_id for item in declared)
        if field not in fields:
            raise KeyError(
                f"{field!r} is not one of the alias's declared fields: {', '.join(fields)}"
            )
        registration = self.__catalog.dataset(str(first.dataset_id))
        require_declared(registration)
        if registration.grain is Grain.ROWS:
            raise TypeError(
                f"dataset {str(first.dataset_id)!r} declares grain: rows, which has no panel; "
                "read it with rows(alias)"
            )
        mismatch = lookback_fits_grain(first.lookback, registration.grain)
        if mismatch is not None:
            raise TypeError(f"dataset {str(first.dataset_id)!r}: {mismatch}")
        keyed_by_instrument = registration.instrument_field is not None
        source = self.__catalog.source(str(registration.source))
        source_digest = self._digest(source.path)
        names = tuple(instruments) if keyed_by_instrument else ()
        identity = panel_identity(
            source_digest, str(first.dataset_id), fields, names, registration.span
        )
        panel = self.__panels.get(identity)
        if panel is None:
            # The registered span bounds the one scan. A registration that was never validated
            # (a test catalog) carries none, so the source's own first and last instants stand in.
            span = registration.span
            if span is None:
                grid = self._instant_grid(source, registration.available_at)
                span = (grid[0], grid[-1]) if grid else (evaluation_time, evaluation_time)
            rows = scan.observation_rows(
                source,
                instrument_field=registration.instrument_field,
                available_at_field=registration.available_at,
                key_fields=registration.key_fields,
                fields={item.field_id: resolve_field(registration, item) for item in declared},
                aggregated=registration.aggregated,
                instruments=instruments,
                # The whole registered span: one scan, and every later window is a slice.
                evaluation_time=span[1],
                lower_bound=span[0],
                session=self.__session,
            )
            panel = self.__panels[identity] = Panel.from_rows(
                rows,
                dataset_id=str(first.dataset_id),
                fields=fields,
                instruments=instruments,
                keyed_by_instrument=keyed_by_instrument,
                identity=identity,
                source_digest=source_digest,
            )
        window = panel.window(field, evaluation_time=evaluation_time, lookback=first.lookback)
        access = AccessRecord(
            consumer_id=consumer_id,
            dataset_id=first.dataset_id,
            source_id=str(source.source_id),
            source_digest=source_digest,
            fields=(field,),
            lookback=first.lookback,
            evaluation_time=evaluation_time,
            instruments=names,
            lower_bound=window.lower_bound,
            actual_rows={name: {field: count} for name, count in window.counts().items()}
            if keyed_by_instrument
            else {},
            max_available_at=window.max_available_at,
        )
        return window, access

    def _instant_grid(self, source: SourceSpec, available_at_field: str) -> tuple[object, ...]:
        """Every distinct instant of one source, ascending; once per run when a session is held."""
        if self.__session is not None:
            return self.__session.instant_grid(source, available_at_field)
        return tuple(
            value for value in scan.distinct_values(source, available_at_field) if value is not None
        )

    def grain(self, requirement: DataRequirement):
        registration = self.__catalog.dataset(str(requirement.dataset_id))
        require_declared(registration)
        return registration.grain

    def _digest(self, path: Path) -> str:
        cached = self.__digests.get(path)
        if cached is None:
            cached = self.__digests[path] = physical_digest(path)
        return cached

    def query_many(
        self,
        requirements: Sequence[DataRequirement],
        *,
        evaluation_time: datetime,
        instruments: Sequence[str],
        consumer_id: str,
    ):
        """Every field an alias declares, in one scan.

        A `DataRequirement` names one field (`docs/issues/049`), and an alias over three fields
        is three requirements. Reading them one at a time was three scans of the same window and
        a join in Python on `(available_at, instrument)` -- the per-declared-input floor
        `docs/issues/046` measured. The requirements all name one dataset and one lookback, which
        is exactly what one `observation_rows` call takes as a `fields` mapping, and the window
        SQL already ranks each field's own last N rows separately, so the fused read returns the
        rows the joined reads did: one row per (instant, instrument) any field admitted, each
        field null outside its own window. One access is recorded, naming every field.
        """
        require_tz_aware(evaluation_time, name="evaluation_time")
        declared = tuple(requirements)
        if not declared:
            raise ValueError("a read requires at least one DataRequirement")
        first = declared[0]
        if any(item.dataset_id != first.dataset_id for item in declared):
            raise ValueError("one read serves one dataset; split requirements by dataset_id")
        if any(item.lookback != first.lookback for item in declared):
            raise ValueError("one read serves one lookback; split requirements by lookback")
        declared_fields = tuple(item.field_id for item in declared)
        if len(set(declared_fields)) != len(declared_fields):
            raise ValueError("a read must not name one field twice")
        registration = self.__catalog.dataset(str(first.dataset_id))
        require_declared(registration)
        keyed_by_instrument = registration.instrument_field is not None
        source = self.__catalog.source(str(registration.source))
        source_digest = self._digest(source.path)
        fields = {item.field_id: resolve_field(registration, item) for item in declared}
        mismatch = lookback_fits_grain(first.lookback, registration.grain)
        if mismatch is not None:
            raise TypeError(f"dataset {str(first.dataset_id)!r}: {mismatch}")
        lower_bound = None
        rows = None
        if isinstance(first.lookback, RowsLookback):
            # A panel lookback: the table's last n instants, the same for every name. The bound
            # is arithmetic on the source's instant grid -- read once per run when a session is
            # held -- and the window SQL then takes every row at or after it. No per-name rank.
            lower_bound = self._grid_bound(
                source, registration.available_at, evaluation_time, first.lookback.rows
            )
        elif isinstance(first.lookback, InstantsLookback):
            # A series lookback: each name's own last n, per field, the way the rows-grain read
            # has always ranked (`PARTITION BY instrument` in `observation_rows`).
            rows = first.lookback.instants
        elif isinstance(first.lookback, CalendarLookback):
            lower_bound = first.lookback.lower_bound(evaluation_time)
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
            dataset_id=first.dataset_id,
            source_id=str(source.source_id),
            source_digest=source_digest,
            fields=declared_fields,
            lookback=first.lookback,
            evaluation_time=evaluation_time,
            instruments=tuple(instruments) if keyed_by_instrument else (),
            lower_bound=lower_bound,
            actual_rows=actual,
            max_available_at=max_available_at,
        )
        # The public constructor validates every cell, which costs about as much as the query
        # that produced them, so take the same trusted door `ModelWindow.snapshot` already uses.
        return ObservationBatch._trusted(normalized, access)
