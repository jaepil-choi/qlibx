"""Turning declared aliases into engine reads, and engine rows back into typed observations.

**One call surface for both Model roles.** A DataModel and a StrategyModel declare their reads the
same way -- `inputs()`, keyed by an alias the author names -- and read them the same way,
`context.read(alias)`. What a StrategyModel additionally receives is what its role needs: the
committed account, its own declared history, the bounds every registered Constraint
projected. The difference between the two roles is that list and nothing else, which is what
`docs/issues/036` decided should be true: *"a DataModel and a StrategyModel should be substantially
similar to use, and the size of the current difference is itself the defect."*

**These three functions came from `_internal/pit_bridge.py`, unchanged.** That module existed so
`strategy_bridge` could serve an authored `read(alias)` while the engine served a differently
shaped `context.window.observations(requirement)` -- two capability surfaces over one
`ModelWindow`, with a translation layer between them. Moving them here does not rewrite them; it
removes the reason a caller had to reach into `_internal` to read the way an author writes.

**Every read still goes through `ModelWindow`.** Nothing here holds a store handle or can reach
one. The window is already bounded to `available_at <= evaluation_time`, carries the consumer id
the framework stamped, and records an `AccessRecord` per requirement -- which is what lets the
Flow state an intent's provenance (`flow/simulation.py::_actual_source_refs`) and derive a
materialization's `available_at` (`flow/stamping.derived_available_at`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from vqapr.authoring import DatasetInput, Observation, requirements_for

__all__ = (
    "declared_rows",
    "observations",
    "requirements_for",
)
# `requirements_for` is authoring's -- one fan-out for every role that declares reads -- and is
# re-exported here because this is where the join that consumes it lives.


def declared_rows(read: object, declaration: DatasetInput) -> tuple[dict[str, object], ...]:
    """Read every field one alias declares, back into one row per (instant, instrument).

    Each field is its own requirement and so its own read. Until a single scan serves several
    fields (`docs/issues/046`), joining them is this bridge's job -- and the join is on the pair
    that identifies an observation, which is the only pair every batch agrees on.
    """
    merged: dict[tuple, dict[str, object]] = {}
    for field, requirement in zip(
        declaration.fields, requirements_for(declaration), strict=True
    ):
        for row in read(requirement):  # type: ignore[operator]
            key = (row["available_at"], row.get("instrument"))
            carried = merged.get(key)
            if carried is None:
                carried = merged[key] = dict.fromkeys(declaration.fields)
                carried["available_at"] = key[0]
                carried["instrument"] = key[1]
            carried[field] = row[field]
    return tuple(merged[key] for key in sorted(merged, key=lambda pair: (pair[0], str(pair[1]))))


def observations(
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
