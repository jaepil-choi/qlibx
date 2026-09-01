"""The three DataModels this showcase registers, written against the shipped surface.

Two of them are real and one is a forgery. `ForgingModel` returns `available_at` on every row,
which is the package's own column, and `materialize` refuses it — that refusal is the point of
the third section of the report, so the model exists to be rejected rather than to be run.
"""

from __future__ import annotations

from vqapr.public import DataModel, DataRequirement, RowsLookback


class ReversalFeatureModel(DataModel):
    """Two-session reversal, keeping both closes so the report can show what was read."""

    def requirements(self):
        return (
            DataRequirement.of(
                "reversal-features",
                "price_daily",
                fields=("close",),
                lookback=RowsLookback(2),
            ),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        closes: dict[str, list[float]] = {}
        for row in observations:
            close = row["close"]
            if close is not None:
                closes.setdefault(str(row["instrument"]), []).append(float(close))
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


class AbsoluteScoreModel(DataModel):
    """Reads the DERIVED dataset, which is what makes the second materialization evidence."""

    def requirements(self):
        return (
            DataRequirement.of(
                "absolute-scores",
                "reversal_features",
                fields=("score",),
                lookback=RowsLookback(1),
            ),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        return tuple(
            {
                "instrument": str(row["instrument"]),
                "abs_score": abs(float(row["score"])),
            }
            for row in observations
            if row["score"] is not None
        )


class ForgingModel(ReversalFeatureModel):
    """Claims its own `available_at`. Registered so the refusal can be shown, never published."""

    def requirements(self):
        return (
            DataRequirement.of(
                "forging-model",
                "price_daily",
                fields=("close",),
                lookback=RowsLookback(2),
            ),
        )

    def compute(self, context):
        return tuple(
            {**row, "available_at": context.window.evaluation_time}
            for row in super().compute(context)
        )
