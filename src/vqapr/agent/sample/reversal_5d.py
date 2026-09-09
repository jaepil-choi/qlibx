"""A five-day reversal on the sample panel.

This Strategy knows nothing about listings, halts, or delistings. Tradability is an execution-time
fact it cannot observe at the callback, so guessing at it here would be wrong (see
`docs/implementations/013-halted-names-do-not-stop-a-rebalance.md`). Eligibility is decided only by
whether the declared lookback is present, which removes a name that has just listed and a name that
has stopped trading without either being a special case.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import (
    DatasetInput,
    Hold,
    Rebalance,
    RowsLookback,
    StrategyModel,
)
from vqapr.portfolio.budgets import Budget, PortfolioDirection

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

    def inputs(self):
        return {
            "prices": DatasetInput(
                dataset_id=DATASET_ID,
                fields=("close",),
                lookback=RowsLookback(rows=LOOKBACK),
            ),
        }

    def decide(self, call):
        # One field of the alias as a window: `instants` x `instruments`, the same six sessions
        # for every name. A name that began trading inside the window, or stopped before it,
        # simply has fewer values -- which is what the completeness guard below reads.
        window = call.read("prices", "close")
        closes: dict[str, list[Decimal]] = {}
        for name in window.instruments:
            # A DOUBLE field arrives as `float`, as the dataset declared it
            # (`docs/issues/archive/088`). The intent below is stated in Decimal, so the crossing
            # happens here, once, and through `str`: `Decimal(0.1)` would inherit the binary
            # expansion.
            closes[name] = [Decimal(str(v)) for v in window.values[name] if v is not None]

        eligible = {name: values for name, values in closes.items() if len(values) == LOOKBACK}
        if len(eligible) < SELECTED:
            return Hold(reason="incomplete-lookback")

        returns = {
            name: values[-1] / values[0] - Decimal(1) for name, values in eligible.items()
        }
        weakest = sorted(returns, key=lambda name: (returns[name], name))[:SELECTED]

        weight = INVESTED / Decimal(SELECTED)
        # Only the economics. The intent id, strategy id, source references and account
        # version are framework facts: an author who minted them could get them wrong, and
        # this file is the one a reader copies against their own dataset.
        return Rebalance(
            target_weights={name: weight for name in sorted(weakest)},
            cash_weight=Decimal(1) - weight * Decimal(SELECTED),
            budget=BUDGET,
        )
