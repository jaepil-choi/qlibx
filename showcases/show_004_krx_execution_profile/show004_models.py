"""The authored DataModel/StrategyModel for show_004, at real module scope.

The engine's loader resolves a registered component by re-importing its module and
looking the class up by name; a class defined inside ``run.py``'s ``main()`` would have
no stable import location and would be refused. This module exists so ``MomentumModel``
and ``MomentumLongOnly`` have one.

``decide()`` returns only ``Hold``/``Rebalance`` -- never a UUID, a strategy id, source
refs, or an account version; ``Project.simulate``/``Project.run_completed`` stamp all of
that framework identity. Cross-callback state (the rebalance count) travels only through
``StrategyResult.next_state`` / ``call.previous_state``, never a mutable ``self`` field.
"""

from __future__ import annotations

from decimal import Decimal

from vqapr.authoring import (
    DataModel,
    DatasetInput,
    DerivedRow,
    Hold,
    Output,
    Rebalance,
    RowsLookback,
    StrategyModel,
    StrategyResult,
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

    def inputs(self) -> dict[str, DatasetInput]:
        return {
            "prices": DatasetInput(
                dataset_id="price_daily",
                fields=("close", "is_supervised"),
                lookback=RowsLookback(rows=LOOKBACK),
            )
        }

    def output(self) -> Output:
        return Output(semantic_fields=("score", "eligible"))

    def compute(self, call) -> tuple[DerivedRow, ...]:
        observations = call.read("prices")
        closes: dict[str, list[float]] = {}
        supervised: dict[str, bool] = {}
        for observation in observations:
            instrument = observation.instrument_id
            close = observation.values.get("close")
            if close is not None:
                closes.setdefault(instrument, []).append(float(close))
            supervised[instrument] = bool(observation.values.get("is_supervised"))
        return tuple(
            DerivedRow(
                instrument_id=instrument,
                values={
                    "score": values[-1] / values[0] - 1.0,
                    "eligible": not supervised.get(instrument, False),
                },
            )
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
