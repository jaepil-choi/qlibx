"""A stop-loss strategy: what it remembers between sessions lives in `self.memory`.

The first session buys every name with a close, equal weight, and writes each name's entry
close into memory. Every session after that compares the newest close with the remembered
entry; a name that fell more than STOP is dropped for the rest of the run and its stop is
recorded, with the session it fired on. Memory is strict JSON -- floats and strings -- restored
before every `decide` and snapshotted after, so a replay of the run sees the same stops.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from vqapr import authoring as va
from vqapr.portfolio.budgets import Budget, PortfolioDirection

DATASET_ID = "sample-prices"
FIELD = "close"
STOP = 0.03  # a 3% fall from the entry close
INVESTED = "0.9"
BUDGET = Budget(PortfolioDirection.LONG_ONLY, Decimal(0), Decimal(1), Decimal(0), Decimal(1))


class SampleStopLoss(va.StrategyModel):
    """Equal weight in every name until a name breaks its stop; then never again."""

    def inputs(self):
        read = va.DatasetInput(dataset_id=DATASET_ID, fields=(FIELD,), lookback=va.RowsLookback(rows=1))
        return {"prices": read}

    def decide(self, call):
        window = call.read("prices", FIELD)
        closes = window.matrix()
        if closes.shape[0] == 0:
            return va.Hold(reason="no close published yet")
        newest = closes[-1]
        latest = {
            name: float(newest[column])
            for column, name in enumerate(window.instruments)
            if np.isfinite(newest[column])
        }

        entry: dict[str, float] = self.memory.setdefault("entry", {})
        stopped: dict[str, str] = self.memory.setdefault("stopped", {})
        session = call.evaluation_time.date().isoformat()

        if not self.memory.get("entered"):
            # The first decision: enter every name at the close it was decided on. The flag,
            # not the emptiness of `entry`, says it happened: a book that has stopped out of
            # every name stays in cash rather than entering again.
            entry.update(latest)
            self.memory["entered"] = True
        for name, price in list(entry.items()):
            if name in latest and latest[name] / price - 1.0 < -STOP:
                stopped[name] = session
                del entry[name]

        held = {name: 1 for name in sorted(entry)}
        if held:
            return va.Rebalance.of(long=held, invested=INVESTED)
        if any(quantity != 0 for quantity in call.account.positions.values()):
            # The last name broke its stop: an all-cash book sells it. A Hold would keep it.
            return va.Rebalance(target_weights={}, cash_weight=Decimal(1), budget=BUDGET)
        return va.Hold(reason="every name has broken its stop; the book stays in cash")
