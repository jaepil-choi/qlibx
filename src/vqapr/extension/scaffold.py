"""Templates emitted by `vqapr new`.

A template must **run as written**. A skeleton that raises on the first callback teaches nothing
and cannot be executed to see the shape of a result, so the emitted file is a complete working
Strategy with exactly one marked place to change.

The template deliberately knows nothing about listings, halts, or delistings. Tradability is an
execution-time fact the callback cannot observe (architecture §10, `docs/implementations/
013-halted-names-do-not-stop-a-rebalance.md`); eligibility falls out of whether the declared
lookback is present, and the venue publishes typed zero-dealt evidence for the rest.
"""

from __future__ import annotations

from vqapr.extension.component import ComponentKind

_STRATEGY_TEMPLATE = '''"""A long-only cross-sectional Strategy.

Registering this file as written succeeds and running it produces a result. Change the marked
signal line to express a different view.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from vqapr.public import (
    Budget,
    DataRequirement,
    EconomicPortfolioIntent,
    IntentSourceRef,
    NoDecision,
    PortfolioDirection,
    PortfolioTarget,
    RowsLookback,
    StrategyModel,
)

STRATEGY_ID = "{component_id}"
DATASET_ID = "{dataset_id}"
LOOKBACK = {lookback}
"""Rows of history each name needs. A five-day return needs six observations, not five."""

INVESTED = Decimal("{invested}")
"""Fraction of NAV held in names; the remainder stays in cash."""

BUDGET = Budget(
    PortfolioDirection.LONG_ONLY,
    Decimal("0"),
    Decimal("1"),
    Decimal("0"),
    Decimal("1"),
)


class {class_name}(StrategyModel):
    """Ranks the cross-section and holds the selected names in equal weight."""

    def requirements(self):
        return (
            DataRequirement.of(
                STRATEGY_ID,
                DATASET_ID,
                fields=("{field}",),
                lookback=RowsLookback(LOOKBACK),
            ),
        )

    def on_occurrence(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        history: dict[str, list[Decimal]] = {{}}
        for row in rows:
            value = row["{field}"]
            if value is not None:
                history.setdefault(str(row["instrument"]), []).append(value)

        # A name is eligible when the declared lookback is fully present. A newly listed name has
        # too few rows and a delisted name stops appearing, so both leave the cross-section here
        # without the Strategy ever asking whether they are tradable.
        eligible = {{
            name: values for name, values in history.items() if len(values) == LOOKBACK
        }}
        if len(eligible) < 2:
            return NoDecision("a cross-sectional view needs at least two names with full history")

        # ---- the one line to change -------------------------------------------------------
        # Five-day reversal: the weakest recent return becomes the largest score.
        scores = {{
            name: -1 * (values[-1] / values[0] - Decimal(1)) for name, values in eligible.items()
        }}
        # -----------------------------------------------------------------------------------

        selected = [name for name, score in scores.items() if score > 0]
        if not selected:
            return NoDecision("no name scored above zero")

        weight = INVESTED / Decimal(len(selected))
        targets = tuple(
            PortfolioTarget(name, weight=weight) for name in sorted(selected)
        )
        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, f"{{STRATEGY_ID}}/{{context.occurrence.occurrence_id}}"),
            STRATEGY_ID,
            targets,
            Decimal(1) - weight * Decimal(len(selected)),
            BUDGET,
            _source_refs(context),
            context.account.version,
            None,
        )


def _source_refs(context):
    """Exactly the sources this callback read, in first-read order.

    The Flow recomputes this from the window and refuses an intent whose provenance disagrees,
    so it must be derived from the accesses rather than declared.
    """
    seen: dict[str, str] = {{}}
    for access in context.window.accesses:
        seen.setdefault(access.source_id, access.source_digest)
    return tuple(IntentSourceRef(source, digest) for source, digest in seen.items())
'''

_DATA_MODEL_TEMPLATE = '''"""A DataModel that derives one column from declared observations."""

from __future__ import annotations

from decimal import Decimal

from vqapr.public import DataModel, DataRequirement, RowsLookback

MODEL_ID = "{component_id}"
DATASET_ID = "{dataset_id}"
LOOKBACK = {lookback}


class {class_name}(DataModel):
    """Emits one derived value per instrument at each materialization time."""

    def requirements(self):
        return (
            DataRequirement.of(
                MODEL_ID,
                DATASET_ID,
                fields=("{field}",),
                lookback=RowsLookback(LOOKBACK),
            ),
        )

    def compute(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        history: dict[str, list[Decimal]] = {{}}
        for row in rows:
            value = row["{field}"]
            if value is not None:
                history.setdefault(str(row["instrument"]), []).append(value)

        # ---- the one line to change -------------------------------------------------------
        # Trailing return over the declared lookback.
        derived = {{
            name: values[-1] / values[0] - Decimal(1)
            for name, values in history.items()
            if len(values) == LOOKBACK
        }}
        # -----------------------------------------------------------------------------------

        return [
            {{"instrument": name, "{output_field}": value}}
            for name, value in sorted(derived.items())
        ]
'''

_TEMPLATES = {
    ComponentKind.STRATEGY_MODEL: _STRATEGY_TEMPLATE,
    ComponentKind.DATA_MODEL: _DATA_MODEL_TEMPLATE,
}


def _class_name(component_id: str) -> str:
    parts = [part for part in component_id.replace("_", "-").split("-") if part]
    if not parts:
        raise ValueError("component_id must contain at least one alphanumeric part")
    return "".join(part[:1].upper() + part[1:] for part in parts)


def render(
    kind: ComponentKind,
    component_id: str,
    *,
    dataset_id: str,
    field: str = "close",
    lookback: int = 6,
    invested: str = "0.9",
    output_field: str = "value",
) -> str:
    """Return a runnable component source for `kind`."""
    if kind not in _TEMPLATES:
        raise ValueError(f"no template for {kind}; user authoring covers datamodel and strategy")
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    return _TEMPLATES[kind].format(
        component_id=component_id,
        class_name=_class_name(component_id),
        dataset_id=dataset_id,
        field=field,
        lookback=lookback,
        invested=invested,
        output_field=output_field,
    )
