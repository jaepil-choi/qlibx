"""The three DataModels this showcase registers, written against the one authoring surface.

Two of them are real and one is a forgery. `ForgingModel` returns `available_at` on every row,
which is the package's own column, and `materialize` refuses it -- that refusal is the point of
the third section of the report, so the model exists to be rejected rather than to be run.
"""

from __future__ import annotations

from vqapr import authoring as va


class ReversalFeatureModel(va.DataModel):
    """Two-session reversal, keeping both closes so the report can show what was read."""

    def inputs(self):
        return {
            "prices": va.DatasetInput(
                dataset_id="price_daily", fields=("close",), lookback=va.RowsLookback(rows=2)
            )
        }

    def compute(self, context):
        closes: dict[str, list[float]] = {}
        for row in context.read("prices"):
            close = row.values["close"]
            if close is not None:
                closes.setdefault(row.instrument_id, []).append(float(close))
        return tuple(
            {
                "instrument": instrument,
                "old_close": values[0],
                "new_close": values[-1],
                "score": -(values[-1] / values[0] - 1.0),
            }
            for instrument, values in sorted(closes.items())
            if len(values) == 2
        )


class AbsoluteScoreModel(va.DataModel):
    """Reads the DERIVED dataset, which is what makes the second materialization evidence."""

    def inputs(self):
        return {
            "scores": va.DatasetInput(
                dataset_id="reversal_features", fields=("score",), lookback=va.RowsLookback(rows=1)
            )
        }

    def compute(self, context):
        return tuple(
            {"instrument": row.instrument_id, "abs_score": abs(float(row.values["score"]))}
            for row in context.read("scores")
            if row.values["score"] is not None
        )


class ForgingModel(ReversalFeatureModel):
    """Claims its own `available_at`. Registered so the refusal can be shown, never published."""

    def compute(self, context):
        return tuple(
            {**row, "available_at": context.evaluation_time}
            for row in super().compute(context)
        )
