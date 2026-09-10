"""A factor portfolio on the firm characteristic a DataModel run published.

Reads `sample-features`.`momentum_5d` -- the dataset scenario ③ wrote -- exactly as it would read
a vendor table: one `DatasetInput`, the newest row per name. Long the three strongest, short the
three weakest, dollar-neutral; the sign of the weight is the side (`Rebalance.signed`).
"""

from __future__ import annotations

import numpy as np

from vqapr import authoring as va

FEATURES = "sample-features"
FIELD = "momentum_5d"
SIDE = 3
GROSS = 1  # $0.5 long, $0.5 short


class SampleFactor(va.StrategyModel):
    """Long the top three by momentum, short the bottom three, equal weight per side."""

    def inputs(self):
        read = va.DatasetInput(dataset_id=FEATURES, fields=(FIELD,), lookback=va.RowsLookback(rows=1))
        return {"features": read}

    def decide(self, call):
        window = call.read("features", FIELD)
        scores = window.matrix()  # one row: the newest characteristic per name
        if scores.shape[0] == 0:
            return va.Hold(reason="no characteristic published yet")
        latest = scores[-1]
        names = window.instruments
        ranked = sorted(
            (latest[column], name) for column, name in enumerate(names) if np.isfinite(latest[column])
        )
        if len(ranked) < 2 * SIDE:
            return va.Hold(reason="fewer than six names carry a characteristic")
        weights = {name: -1.0 / SIDE for _, name in ranked[:SIDE]}
        weights.update({name: 1.0 / SIDE for _, name in ranked[-SIDE:]})
        return va.Rebalance.signed(dict(sorted(weights.items())), gross=GROSS)
