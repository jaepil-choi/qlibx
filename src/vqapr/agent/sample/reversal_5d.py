"""A five-day reversal on the sample panel.

This Strategy knows nothing about listings, halts, or delistings. Tradability is an execution-time
fact it cannot observe at the callback, so guessing at it here would be wrong (see
`docs/implementations/013-halted-names-do-not-stop-a-rebalance.md`). Eligibility is decided only by
whether the declared lookback is present, which removes a name that has just listed and a name that
has stopped trading without either being a special case.
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

STRATEGY_ID = "sample-reversal-5d"
DATASET_ID = "sample-prices"
LOOKBACK = 6
"""A five-day return compares the newest close with the close five sessions earlier."""

INVESTED = Decimal("0.9")
SELECTED = 3

BUDGET = Budget(
    PortfolioDirection.LONG_ONLY,
    Decimal("0"),
    Decimal("1"),
    Decimal("0"),
    Decimal("1"),
)


class SampleReversal5d(StrategyModel):
    """Buys the weakest recent performers in equal weight."""

    def requirements(self):
        return (
            DataRequirement.of(
                STRATEGY_ID,
                DATASET_ID,
                fields=("close",),
                lookback=RowsLookback(LOOKBACK),
            ),
        )

    def on_occurrence(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[Decimal]] = {}
        for row in rows:
            if row["close"] is not None:
                # `Decimal(str(v))` rather than the raw cell: this file is copied against the
                # reader's own dataset, and a parquet float64 column arrives as `float`, which
                # raises on the `values[-1] / values[0] - Decimal(1)` below. The sample panel is
                # decimal128, so the bug is invisible here and appears only after the copy.
                closes.setdefault(str(row["instrument"]), []).append(Decimal(str(row["close"])))

        eligible = {name: values for name, values in closes.items() if len(values) == LOOKBACK}
        if len(eligible) < SELECTED:
            return NoDecision(f"fewer than {SELECTED} names carry the full lookback")

        returns = {
            name: values[-1] / values[0] - Decimal(1) for name, values in eligible.items()
        }
        weakest = sorted(returns, key=lambda name: (returns[name], name))[:SELECTED]

        weight = INVESTED / Decimal(SELECTED)
        targets = tuple(PortfolioTarget(name, weight=weight) for name in sorted(weakest))
        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, f"{STRATEGY_ID}/{context.occurrence.occurrence_id}"),
            STRATEGY_ID,
            targets,
            Decimal(1) - weight * Decimal(SELECTED),
            BUDGET,
            _source_refs(context),
            context.account.version,
            None,
        )


def _source_refs(context):
    """Exactly the sources this callback read, in first-read order."""
    seen: dict[str, str] = {}
    for access in context.window.accesses:
        seen.setdefault(access.source_id, access.source_digest)
    return tuple(IntentSourceRef(source, digest) for source, digest in seen.items())
