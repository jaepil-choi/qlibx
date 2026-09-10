"""A five-day reversal on the sample panel.

This Strategy knows nothing about listings, halts, or delistings. Tradability is an execution-time
fact it cannot observe at the callback, so guessing at it here would be wrong (see
`docs/implementations/013-halted-names-do-not-stop-a-rebalance.md`). Eligibility is decided only by
whether the declared lookback is present, which removes a name that has just listed and a name that
has stopped trading without either being a special case.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

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
        # for every name. `matrix()` is that window as one float array -- rows are the sessions
        # (the last row is the newest), columns are `window.instruments`, NaN where a name had
        # no close -- so the five-day return is one expression over every name at once, and
        # ten names cost what three thousand do.
        window = call.read("prices", "close")
        closes = window.matrix()

        # A name that began trading inside the window, or stopped before it, has a NaN in its
        # column; the completeness guard reads exactly that, and nothing else about the name.
        complete = np.isfinite(closes).all(axis=0) & (closes.shape[0] == LOOKBACK)
        if int(complete.sum()) < SELECTED:
            return Hold(reason="incomplete-lookback")

        returns = closes[-1] / closes[0] - 1.0
        # The weakest names, ties broken by id so a replay picks the same three.
        ranked = sorted(
            (returns[column], name)
            for column, name in enumerate(window.instruments)
            if complete[column]
        )
        weakest = [name for _, name in ranked[:SELECTED]]

        # Only the economics, and Decimal only here, at the intent boundary: the framework's
        # arithmetic on weights is exact, the signal's is float. The intent id, strategy id,
        # source references and account version are framework facts: an author who minted them
        # could get them wrong, and this file is the one a reader copies against their own
        # dataset.
        weight = INVESTED / Decimal(SELECTED)
        return Rebalance(
            target_weights={name: weight for name in sorted(weakest)},
            cash_weight=Decimal(1) - weight * Decimal(SELECTED),
            budget=BUDGET,
        )
