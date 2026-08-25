"""Serve declared aliases from the real point-in-time store.

`agent_first` deliberately resolves nothing itself: it takes an injected resolver so the
invocation boundary can be tested without a database. That injection point is what this
module fills in production. It translates one `authoring.DatasetInput` into the retained
engine's `DataRequirement`, runs the bounded physical query, and hands back typed
`Observation` values.

The translation is deliberately narrow. It does not widen a lookback, invent a field, or
fall back to a different dataset: a declaration the store cannot serve is an error, never
an empty result that looks like a legitimately quiet day.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from vqapr.authoring import DatasetInput, Observation

__all__ = (
    "CatalogResolver",
    "StoreResolver",
    "engine_lookback",
    "observation_rows",
    "requirement_for",
)


def engine_lookback(declaration_lookback: object):
    """Translate an authoring lookback into the engine's own lookback type.

    `authoring.RowsLookback` and `data.lookback.RowsLookback` are deliberately separate
    types: the authoring one is a public contract, the engine one is private. They carry
    the same economics, so this is a pure translation - it never widens a window or
    substitutes a different lookback kind.
    """
    from vqapr.authoring import CalendarLookback as AuthoringCalendar
    from vqapr.authoring import RowsLookback as AuthoringRows
    from vqapr.data.lookback import CalendarLookback as EngineCalendar
    from vqapr.data.lookback import RowsLookback as EngineRows

    if isinstance(declaration_lookback, AuthoringRows):
        return EngineRows(rows=declaration_lookback.rows)
    if isinstance(declaration_lookback, AuthoringCalendar):
        return EngineCalendar(
            years=declaration_lookback.years,
            months=declaration_lookback.months,
            days=declaration_lookback.days,
            timezone=declaration_lookback.timezone,
        )
    raise TypeError(
        "lookback must be an authoring.RowsLookback or authoring.CalendarLookback; "
        f"got {type(declaration_lookback).__name__}"
    )


def requirement_for(consumer_id: str, declaration: DatasetInput):
    """Translate one declared alias into the retained engine's requirement type."""
    from vqapr.data.requirements import DataRequirement

    if not isinstance(declaration, DatasetInput):
        raise TypeError("declaration must be an authoring.DatasetInput")
    return DataRequirement.of(
        consumer_id,
        declaration.dataset_id,
        fields=declaration.fields,
        lookback=engine_lookback(declaration.lookback),
    )


def observation_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    instrument_field: str,
    available_at_field: str,
    fields: Sequence[str],
) -> tuple[Observation, ...]:
    """Project engine rows onto typed observations, carrying only declared fields.

    A row missing its instrument or availability stamp is a schema error rather than a row
    to skip: dropping it silently would turn a broken declaration into a thin result.
    """
    observations: list[Observation] = []
    for row in rows:
        if instrument_field not in row:
            raise KeyError(
                f"row is missing the instrument field {instrument_field!r}; "
                "the dataset declaration does not match the physical table"
            )
        if available_at_field not in row:
            raise KeyError(
                f"row is missing the availability field {available_at_field!r}; "
                "the dataset declaration does not match the physical table"
            )
        available_at = row[available_at_field]
        if not isinstance(available_at, datetime):
            raise TypeError(
                f"{available_at_field!r} must be a timezone-aware datetime, "
                f"got {type(available_at).__name__}"
            )
        values = {}
        for field in fields:
            if field not in row:
                raise KeyError(
                    f"row is missing the declared field {field!r}; a Model reads only what "
                    "it declared, so a missing declared field is a schema error"
                )
            values[field] = row[field]
        observations.append(
            Observation(
                instrument_id=str(row[instrument_field]),
                available_at=available_at,
                values=values,
            )
        )
    return tuple(observations)


class CatalogResolver:
    """Serve declared aliases from whatever the catalog says a dataset actually is.

    A caller declares `DatasetInput(dataset_id=...)` and should not have to know whether
    that id names a physical parquet they registered or a derived dataset an earlier
    materialization persisted. The catalog already records which it is, so the dispatch
    belongs here rather than in every caller.

    Point-in-time filtering and lookback trimming are applied identically on both paths:
    an observation is visible only if its availability is at or before the evaluation
    time, and at most `lookback.rows` of them survive per instrument. Leaving that to
    callers is how two consumers of the same dataset end up disagreeing about what was
    knowable when.
    """

    __slots__ = ("_instruments", "_project")

    def __init__(self, project, *, instruments: Sequence[str]) -> None:
        self._project = project
        self._instruments = tuple(instruments)
        if not self._instruments:
            raise ValueError("instruments must be a non-empty sequence")

    def __call__(
        self, alias: str, declaration: DatasetInput, evaluation_time: datetime
    ) -> tuple[Observation, ...]:
        from vqapr.authoring import RowsLookback

        if not isinstance(declaration.lookback, RowsLookback):
            raise TypeError(
                "CatalogResolver supports RowsLookback only; a calendar window needs the "
                "engine-backed StoreResolver"
            )
        binding = self._project.catalog().dataset(declaration.dataset_id)
        if binding.get("derived"):
            return self._from_persisted(declaration, evaluation_time)
        return self._from_physical(binding, declaration, evaluation_time)

    def _from_persisted(
        self, declaration: DatasetInput, evaluation_time: datetime
    ) -> tuple[Observation, ...]:
        rows = self._project.read_output(declaration.dataset_id)
        grouped: dict[str, list[Observation]] = {}
        for row in rows:
            available_at = datetime.fromisoformat(str(row["evaluation_time"]))
            if available_at > evaluation_time:
                continue
            instrument_id = str(row["instrument_id"])
            if instrument_id not in self._instruments:
                continue
            raw = row["values"]
            missing = [field for field in declaration.fields if field not in raw]
            if missing:
                raise KeyError(
                    f"persisted dataset {declaration.dataset_id!r} is missing declared "
                    f"fields {missing}"
                )
            grouped.setdefault(instrument_id, []).append(
                Observation(
                    instrument_id=instrument_id,
                    available_at=available_at,
                    values={field: raw[field] for field in declaration.fields},
                )
            )
        return _trimmed(grouped, declaration.lookback.rows)

    def _from_physical(
        self, binding: Mapping[str, object], declaration: DatasetInput, evaluation_time: datetime
    ) -> tuple[Observation, ...]:
        import duckdb

        path = binding.get("path")
        if not path:
            raise KeyError(
                f"dataset {declaration.dataset_id!r} has no registered path to read from"
            )
        instrument_field = str(binding["instrument_field"])
        available_at_field = str(binding["available_at_field"])
        physical = {
            field: str(dict(binding["fields"])[field]) for field in declaration.fields
        }
        columns = ", ".join(
            [f'"{instrument_field}"', f'"{available_at_field}"']
            + [f'"{column}" AS "{field}"' for field, column in physical.items()]
        )
        placeholders = ", ".join("?" for _ in self._instruments)
        query = (
            f"SELECT {columns} FROM read_parquet(?) "
            f'WHERE "{available_at_field}" <= ? AND "{instrument_field}" IN ({placeholders})'
        )
        connection = duckdb.connect()
        try:
            cursor = connection.execute(
                query, [str(path), evaluation_time, *self._instruments]
            )
            names = [description[0] for description in cursor.description]
            rows = [dict(zip(names, record, strict=True)) for record in cursor.fetchall()]
        finally:
            connection.close()

        grouped: dict[str, list[Observation]] = {}
        for row in rows:
            grouped.setdefault(str(row[instrument_field]), []).append(
                Observation(
                    instrument_id=str(row[instrument_field]),
                    available_at=row[available_at_field],
                    values={field: row[field] for field in declaration.fields},
                )
            )
        return _trimmed(grouped, declaration.lookback.rows)


def _trimmed(
    grouped: Mapping[str, list[Observation]], rows: int
) -> tuple[Observation, ...]:
    """Keep at most `rows` most-recent observations per instrument, oldest first."""
    observations: list[Observation] = []
    for instrument in sorted(grouped):
        window = sorted(grouped[instrument], key=lambda item: item.available_at)
        observations.extend(window[-rows:])
    return tuple(observations)


class StoreResolver:
    """An `ObservationResolver` backed by the real PIT store.

    Instantiated once per materialization or run and passed into the invocation boundary,
    so every callback reads through the same bounded, provenance-recording path.
    """

    __slots__ = ("_consumer_id", "_instruments", "_store")

    def __init__(self, store, *, consumer_id: str, instruments: Sequence[str]) -> None:
        self._store = store
        self._consumer_id = consumer_id
        self._instruments = tuple(instruments)

    def __call__(
        self, alias: str, declaration: DatasetInput, evaluation_time: datetime
    ) -> tuple[Observation, ...]:
        requirement = requirement_for(self._consumer_id, declaration)
        batch = self._store.query(
            requirement,
            evaluation_time=evaluation_time,
            instruments=self._instruments,
        )
        registration = self._store_registration(declaration.dataset_id)
        return observation_rows(
            batch.rows,
            instrument_field=registration["instrument_field"],
            available_at_field=registration["available_at_field"],
            fields=declaration.fields,
        )

    def _store_registration(self, dataset_id: str) -> Mapping[str, str]:
        """The physical field names the engine already resolved for this dataset.

        The engine's registration calls the availability column `available_at`, while the
        public declaration calls it `available_at_field`. The rename is deliberate on the
        public side, so the mapping happens here rather than by guessing either name.
        """
        registration = self._store._DuckDbObservationStore__catalog.dataset(str(dataset_id))
        return {
            "instrument_field": registration.instrument_field,
            "available_at_field": registration.available_at,
        }
