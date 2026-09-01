"""Turning declared aliases into engine reads, and engine rows back into typed observations.

**One call surface for both Model roles.** A DataModel and a StrategyModel declare their reads the
same way -- `inputs()`, keyed by an alias the author names -- and read them the same way,
`context.read(alias)`. What a StrategyModel additionally receives is what its role needs: the
committed account, the state it returned last time, the bounds every registered Constraint
projected. The difference between the two roles is that list and nothing else, which is what
`docs/issues/036` decided should be true: *"a DataModel and a StrategyModel should be substantially
similar to use, and the size of the current difference is itself the defect."*

**This used to live under `_internal`.** `_internal/models/agent_first.py` built a private
`DataCall`/`StrategyCall` pair so that `strategy_bridge` could hand one to an authored `decide()`,
while the engine handed a differently-shaped context to `on_occurrence()`. Two capability surfaces
over one `ModelWindow`, and a module whose whole job was to sit between them. The projection below
is that module's code; what changed is that the engine owns it, so there is nothing to translate.

**Every read still goes through `ModelWindow`.** These functions hold no store handle and no way to
reach one. The window is already bounded to `available_at <= evaluation_time` and records an
`AccessRecord` per requirement, which is what lets the Flow stamp an intent's provenance
(`flow/simulation.py::_actual_source_refs`) and derive a materialization's `available_at`
(`flow/stamping.derived_available_at`). A read that bypassed it would produce a value whose
provenance the run cannot state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from vqapr.authoring import DatasetInput, Observation
from vqapr.data.requirements import DataRequirement

INSTRUMENT_FIELD = "instrument"
AVAILABLE_AT_FIELD = "available_at"
"""What the engine names the two columns every observation row carries.

Fixed rather than passed, because they are not the dataset's physical column names -- the
registration already mapped those. By the time a row reaches here it is in framework vocabulary,
and a caller supplying a different pair would be describing a row shape that does not occur.
"""


def requirements_for(
    consumer_id: str, declarations: Mapping[str, DatasetInput]
) -> dict[str, tuple[DataRequirement, ...]]:
    """Every engine requirement each declared alias adds up to, keyed by alias.

    **The fan-out lives here, alone, and it returns a tuple on purpose.** One alias becomes one
    requirement today. `docs/issues/049` settles that a requirement names `(dataset_id, field_id)`,
    so an alias declaring three fields will become three requirements — and when that lands, this
    function is the only place that changes, because callers already receive a tuple and `read()`
    already joins whatever it is given.

    `consumer_id` is the component's own id, stamped by the framework rather than written by the
    author. An author who had to name themselves could name themselves wrong, and it is a value
    the loader already holds.
    """
    resolved: dict[str, tuple[DataRequirement, ...]] = {}
    for alias, declaration in declarations.items():
        if not isinstance(declaration, DatasetInput):
            raise TypeError(
                f"inputs()[{alias!r}] must be a DatasetInput; got {type(declaration).__name__}"
            )
        resolved[alias] = (
            DataRequirement.of(
                consumer_id,
                declaration.dataset_id,
                fields=declaration.fields,
                lookback=declaration.lookback,
            ),
        )
    return resolved


def observations(
    rows: Sequence[Mapping[str, object]], *, fields: Sequence[str]
) -> tuple[Observation, ...]:
    """Project engine rows onto typed observations, carrying only the declared fields.

    Detached on the way out: an author holding an `Observation` cannot reach back into the batch
    the store returned, so nothing a callback does to it can change what a later reader sees.
    """
    projected: list[Observation] = []
    for index, row in enumerate(rows):
        instrument = row.get(INSTRUMENT_FIELD)
        if not isinstance(instrument, str) or not instrument:
            raise TypeError(
                f"row {index}: {INSTRUMENT_FIELD!r} must be a non-empty instrument identifier"
            )
        available_at = row.get(AVAILABLE_AT_FIELD)
        if not isinstance(available_at, datetime):
            raise TypeError(
                f"row {index}: {AVAILABLE_AT_FIELD!r} must be a timezone-aware datetime"
            )
        projected.append(
            Observation(
                instrument_id=instrument,
                available_at=available_at,
                values={field: row.get(field) for field in fields},
            )
        )
    return tuple(projected)
