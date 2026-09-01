"""Translate a declared alias into the engine's own reads.

`agent_first` deliberately resolves nothing itself: it takes an injected resolver so the
invocation boundary can be tested without a database. `strategy_bridge` fills that point in
production, and these are the three translations it needs — one `authoring.DatasetInput` into
the engine's `DataRequirement`, one lookback across the public/private boundary, and one batch
of engine rows back into typed `Observation` values.

The translation is deliberately narrow. It does not widen a lookback, invent a field, or
fall back to a different dataset: a declaration the store cannot serve is an error, never
an empty result that looks like a legitimately quiet day.

**Two resolver classes used to live here and record `124` removed them.** `CatalogResolver`
read through the catalog that went with `project.py`; `StoreResolver` claimed in its own
docstring to be the production injection point and had no importer anywhere in `src/`. What
`strategy_bridge` actually calls is the functions below.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from vqapr.authoring import DatasetInput, Observation

__all__ = (
    "observation_rows",
    "requirement_for",
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
        lookback=declaration.lookback,
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
