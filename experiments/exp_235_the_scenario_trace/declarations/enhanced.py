"""An enhanced index from a saved alpha: benchmark plus a slice of the published factor weights.

The factor run (scenario ④) published its allocation as the dataset `sample-factor-weights`,
one row per name per decision, `weight` signed. This strategy reads it like any other dataset
and tilts an equal-weight benchmark by ACTIVE times that alpha, floored at zero: a long-only
index with a factor lean, on the sample venue.
"""

from __future__ import annotations

import numpy as np

from vqapr import authoring as va

ALPHA = "sample-factor-weights"
PRICES = "sample-prices"
ACTIVE = 0.5  # how much of the alpha's weight the index takes on


class SampleEnhancedIndex(va.StrategyModel):
    """Equal-weight benchmark tilted by half the published factor weights, long-only."""

    def inputs(self):
        return {
            "alpha": va.DatasetInput(dataset_id=ALPHA, fields=("weight",), lookback=va.RowsLookback(rows=1)),
            "prices": va.DatasetInput(dataset_id=PRICES, fields=("close",), lookback=va.RowsLookback(rows=1)),
        }

    def decide(self, call):
        prices = call.read("prices", "close")
        closes = prices.matrix()
        if closes.shape[0] == 0:
            return va.Hold(reason="no close published yet")
        universe = [
            name for column, name in enumerate(prices.instruments) if np.isfinite(closes[-1][column])
        ]
        benchmark = {name: 1.0 / len(universe) for name in universe}

        alpha = call.read("alpha", "weight")
        signed = alpha.matrix()
        if signed.shape[0] == 0:
            return va.Hold(reason="the factor run has published no weight yet")
        active = {
            name: float(signed[-1][column])
            for column, name in enumerate(alpha.instruments)
            if np.isfinite(signed[-1][column])
        }

        tilted = {
            name: max(0.0, benchmark[name] + ACTIVE * active.get(name, 0.0)) for name in universe
        }
        chosen = {name: weight for name, weight in sorted(tilted.items()) if weight > 0}
        return va.Rebalance.of(long=chosen, invested="1")
