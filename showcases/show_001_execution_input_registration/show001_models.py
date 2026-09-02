"""The authored StrategyModel for show_001, at real module scope.

The engine's loader resolves a registered component by re-importing its module and
looking the class up by name; a class defined inside `run.py`'s `main()` would have no
stable import location and would be refused. This module exists solely so
`ShowcaseStrategy` has one.

`decide()` returns only `Hold`/`Rebalance` - never a UUID, strategy id, source refs, or
account version. The framework stamps all of that identity; the author's only job is the
economic decision.

**It declares one dataset read, and the read is real.** A declaration nothing consumes would
be a lie, so the decision is conditioned on the close actually being there: no observed
price, no book. Whether the book was already issued lives in `self.memory`, which the
framework restores before every `decide()` and snapshots after it.
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

BUDGET = Budget(
    direction=PortfolioDirection.LONG_ONLY,
    cash_lower=Decimal(0),
    cash_upper=Decimal(1),
    target_lower=Decimal(0),
    target_upper=Decimal(1),
)


class ShowcaseStrategy(StrategyModel):
    """Holds half the book on the first decision, then holds the position steady.

    Mirrors the legacy showcase strategy's economics: issue one demonstrated intent, then
    go idle once it is pending or executed.
    """

    def inputs(self):
        return {
            "prices": DatasetInput(
                dataset_id="price_daily",
                fields=("close",),
                lookback=RowsLookback(rows=1),
            ),
        }

    def decide(self, call) -> Hold | Rebalance:
        if self.memory is not None:
            return Hold(reason="already-issued")
        if not call.read("prices", "close").latest():
            return Hold(reason="no-observed-price")
        self.memory = {"issued": True}
        return Rebalance(
            target_weights={"A": Decimal("0.5")},
            cash_weight=Decimal("0.5"),
            budget=BUDGET,
        )
