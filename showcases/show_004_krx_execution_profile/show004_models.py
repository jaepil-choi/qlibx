"""The authored DataModel/StrategyModel for show_004, at real module scope.

The engine's loader resolves a registered component by re-importing its module and
looking the class up by name; a class defined inside ``run.py``'s ``main()`` would have
no stable import location and would be refused. This module exists so ``MomentumModel``
and ``MomentumLongOnly`` have one.

``decide()`` returns only ``Hold``/``Rebalance`` -- never a UUID, a strategy id, source
refs, or an account version; the framework stamps all of that identity. Cross-callback state
(the rebalance count) travels only through ``StrategyResult.next_state`` /
``call.previous_state``, never a mutable ``self`` field.

**The two models are written against different contracts, and that is not an oversight.** A
StrategyModel may be authored against ``vqapr.authoring`` because the loader adapts it; a
DataModel may not, so ``MomentumModel`` implements ``vqapr.public.DataModel`` directly. The
split is the framework's, not this showcase's.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import (
    DatasetInput,
    Hold,
    Rebalance,
    RowsLookback,
    StrategyModel,
    StrategyResult,
)
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.public import DataModel, DataRequirement
from vqapr.public import RowsLookback as EngineRowsLookback

LOOKBACK = 6
"""Five-session momentum needs six closes."""

BOOK = 2
"""Equal-weight top-2 momentum book."""

INVESTED = Decimal("0.98")
"""98% invested, 2% cash buffer -- see README for why exact-zero cash_target is avoided."""

CASH_TARGET = Decimal("1") - INVESTED

BUDGET = Budget(
    direction=PortfolioDirection.LONG_ONLY,
    cash_lower=Decimal("0"),
    cash_upper=Decimal("1"),
    target_lower=Decimal("0"),
    target_upper=Decimal("1"),
)


class MomentumModel(DataModel):
    """5-session momentum on real closes, skipping supervised names."""

    def requirements(self):
        return (
            DataRequirement.of(
                "momentum-model",
                "price_daily",
                fields=("close", "is_supervised"),
                lookback=EngineRowsLookback(LOOKBACK),
            ),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[float]] = {}
        supervised: dict[str, bool] = {}
        for row in observations:
            instrument = str(row["instrument"])
            close = row["close"]
            if close is not None:
                closes.setdefault(instrument, []).append(float(close))
            supervised[instrument] = bool(row["is_supervised"])
        return tuple(
            {
                "instrument": instrument,
                "score": values[-1] / values[0] - 1.0,
                "eligible": not supervised.get(instrument, False),
            }
            for instrument, values in sorted(closes.items())
            if len(values) == LOOKBACK and values[0] > 0.0
        )


class MomentumLongOnly(StrategyModel):
    """Equal-weight top-2 momentum book, long only so both profiles can execute it."""

    def inputs(self) -> dict[str, DatasetInput]:
        return {
            "momentum_score": DatasetInput(
                dataset_id="momentum_score",
                fields=("score", "eligible"),
                lookback=RowsLookback(rows=1),
            )
        }

    def decide(self, call) -> StrategyResult:
        latest = {
            observation.instrument_id: float(observation.values["score"])
            for observation in call.read("momentum_score")
            if observation.values.get("score") is not None
            and bool(observation.values.get("eligible"))
        }
        previous = call.previous_state if isinstance(call.previous_state, dict) else {}
        if len(latest) < BOOK:
            return StrategyResult(
                decision=Hold(reason="not-enough-eligible-names"),
                next_state=previous,
                diagnostics={},
            )

        ranked = sorted(latest.items(), key=lambda item: (-item[1], item[0]))
        chosen = {instrument for instrument, _ in ranked[:BOOK]}
        weight = INVESTED / Decimal(BOOK)
        target_weights = {
            instrument: (weight if instrument in chosen else Decimal("0"))
            for instrument in sorted(latest)
        }

        next_state = {**previous, "rebalances": int(previous.get("rebalances", 0)) + 1}
        return StrategyResult(
            decision=Rebalance(
                target_weights=target_weights,
                cash_weight=CASH_TARGET,
                budget=BUDGET,
            ),
            next_state=next_state,
            diagnostics={},
        )
