"""A firm characteristic per name per session: the five-day return (momentum), from `sample-prices`.

A DataModel run walks the strategy clock alone (no market clock): each session it reads the
window and returns one row per name; the framework stamps `available_at` and, at the end,
registers the output as a dataset any later run can declare as an input.
"""

from __future__ import annotations

import numpy as np

from vqapr import public as vq

DATASET_ID = "sample-prices"
FIELD = "close"
LOOKBACK = 6  # six closes: the newest against the one five sessions earlier


class SampleFeatures(vq.DataModel):
    """`momentum_5d` for every name whose six-session window is complete."""

    def inputs(self):
        read = vq.DatasetInput(
            dataset_id=DATASET_ID, fields=(FIELD,), lookback=vq.RowsLookback(rows=LOOKBACK)
        )
        return {"prices": read}

    def compute(self, context):
        window = context.read("prices", FIELD)
        closes = window.matrix()  # instants x names, newest row last, NaN where absent
        if closes.shape[0] < LOOKBACK:
            return []  # warm-up: this session contributes no row
        complete = np.isfinite(closes).all(axis=0) & (closes[0] > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            momentum = closes[-1] / closes[0] - 1.0
        return [
            {"instrument": name, "momentum_5d": float(momentum[column])}
            for column, name in enumerate(window.instruments)
            if complete[column]
        ]
