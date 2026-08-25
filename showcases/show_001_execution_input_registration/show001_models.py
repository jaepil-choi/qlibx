"""The authored StrategyModel for show_001, at real module scope.

The engine's loader resolves a registered component by re-importing its module and
looking the class up by name; a class defined inside `run.py`'s `main()` would have no
stable import location and would be refused. This module exists solely so
`ShowcaseStrategy` has one.

`decide()` returns only `Hold`/`Rebalance` - never a UUID, strategy id, source refs, or
account version. `Project.simulate` stamps all of that framework identity; the author's
only job is the economic decision.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import Hold, Rebalance, StrategyModel, StrategyResult
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

    def decide(self, call: object) -> StrategyResult:
        if call.previous_state is not None:
            return StrategyResult(
                decision=Hold(reason="already-issued"),
                next_state=call.previous_state,
                diagnostics={},
            )
        return StrategyResult(
            decision=Rebalance(
                target_weights={"A": Decimal("0.5")},
                cash_weight=Decimal("0.5"),
                budget=BUDGET,
            ),
            next_state={"issued": True},
            diagnostics={},
        )
