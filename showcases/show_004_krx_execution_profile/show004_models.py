"""The authored DataModel/StrategyModel for show_004, at real module scope.

The engine's loader resolves a registered component by re-importing its module and
looking the class up by name; a class defined inside ``run.py``'s ``main()`` would have
no stable import location and would be refused. This module exists so ``MomentumModel``
and ``MomentumLongOnly`` have one.

``decide()`` returns only ``Hold``/``Rebalance`` -- never a UUID, a strategy id, source
refs, or an account version; the framework stamps all of that identity. Cross-callback state
(the rebalance count) lives in ``self.memory``, which the framework restores before every
callback and snapshots after it.

Both models are written against ``vqapr.authoring``. They used to be written against two
contracts -- the loader adapted an authored StrategyModel and refused an authored DataModel --
and this docstring recorded that as the framework's split, not the showcase's. Record ``131``
closed it.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import (
    DataModel,
    DatasetInput,
    Hold,
    Rebalance,
    RowsLookback,
    StrategyModel,
)
from vqapr.portfolio.budgets import Budget, PortfolioDirection

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

    def inputs(self):
        return {
            "prices": DatasetInput(
                dataset_id="price_daily",
                fields=("close", "is_supervised"),
                lookback=RowsLookback(rows=LOOKBACK),
            )
        }

    def compute(self, context):
        closes: dict[str, list[float]] = {}
        supervised: dict[str, bool] = {}
        for row in context.read("prices"):
            instrument = row.instrument_id
            close = row.values["close"]
            if close is not None:
                closes.setdefault(instrument, []).append(float(close))
            supervised[instrument] = bool(row.values["is_supervised"])
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

    def decide(self, call) -> Hold | Rebalance:
        latest = {
            observation.instrument_id: float(observation.values["score"])
            for observation in call.read("momentum_score")
            if observation.values.get("score") is not None
            and bool(observation.values.get("eligible"))
        }
        previous = self.memory if isinstance(self.memory, dict) else {}
        if len(latest) < BOOK:
            return Hold(reason="not-enough-eligible-names")

        ranked = sorted(latest.items(), key=lambda item: (-item[1], item[0]))
        chosen = {instrument for instrument, _ in ranked[:BOOK]}
        weight = INVESTED / Decimal(BOOK)
        target_weights = {
            instrument: (weight if instrument in chosen else Decimal("0"))
            for instrument in sorted(latest)
        }

        self.memory = {**previous, "rebalances": int(previous.get("rebalances", 0)) + 1}
        return Rebalance(
            target_weights=target_weights,
            cash_weight=CASH_TARGET,
            budget=BUDGET,
        )
