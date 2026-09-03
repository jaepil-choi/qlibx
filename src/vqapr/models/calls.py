"""Turning engine rows back into the typed observations an author reads.

**One call surface for both Model roles.** A DataModel and a StrategyModel declare their reads the
same way -- `inputs()`, keyed by an alias the author names -- and read them the same way,
`context.read(alias)`. What a StrategyModel additionally receives is what its role needs: the
committed account, its own declared history, the bounds every registered Constraint projected.
The difference between the two roles is that list and nothing else, which is what
`docs/issues/036` decided should be true.

**One alias is one scan.** An alias over several fields is several `DataRequirement`s
(`docs/issues/049`: a requirement names one field), and `ModelWindow.declared` reads them in one
statement -- the store's window SQL ranks each field's own last N rows, so the rows come back
already joined on `(instant, instrument)`. The Python join that used to sit here, one read per
field and a merge on that pair, was the per-declared-input floor `docs/issues/046` measured; lane
D removed it (record `136`).

**Every read still goes through `ModelWindow`.** Nothing here holds a store handle or can reach
one. The window is already bounded to `available_at <= evaluation_time`, carries the consumer id
the framework stamped, and records an `AccessRecord` per read -- which is what lets the Flow state
an intent's provenance (`flow/callback.py::_actual_source_refs`) and derive a materialization's
`available_at` (`flow/stamping.derived_available_at`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from vqapr.authoring import Observation, requirements_for

__all__ = (
    "observations",
    "requirements_for",
)
# `requirements_for` is authoring's -- one fan-out for every role that declares reads -- and is
# re-exported here because this is where the join that consumes it lives.


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

    The observations are built through `Observation._framework_row`, without per-row validation.
    `fields` are the alias's declared names, checked once when the `DatasetInput` was declared;
    the scan already returned `available_at` from a `TIMESTAMPTZ` column and the instrument as
    text. `docs/issues/054` measured the validated constructor at 70% of a `rows` read -- 14.6M
    whitespace checks for 159k rows -- re-proving per row what registration proved once.
    """
    declared = tuple(fields)
    build = Observation._framework_row
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
        # One attribute read per row, kept because this function takes rows from any caller:
        # the scan's `TIMESTAMPTZ` column cannot hold a naive value, a test fixture can.
        if available_at.tzinfo is None:
            raise ValueError(f"{available_at_field!r} must be a timezone-aware datetime")
        values: dict[str, object] = {}
        for field in declared:
            if field not in row:
                raise KeyError(
                    f"row is missing the declared field {field!r}; a Model reads only what "
                    "it declared, so a missing declared field is a schema error"
                )
            values[field] = row[field]
        observations.append(build(str(row[instrument_field]), available_at, values))
    return tuple(observations)
