from __future__ import annotations

from vqapr.public import DataModel, DataRequirement, RowsLookback


class ReversalFeatureModel(DataModel):
    def requirements(self):
        return (
            DataRequirement.of(
                "reversal-feature",
                "price_daily",
                fields=("close",),
                lookback=RowsLookback(2),
            ),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        by_instrument: dict[str, list[float]] = {}
        for row in observations:
            if row["close"] is not None:
                by_instrument.setdefault(str(row["instrument"]), []).append(float(row["close"]))
        return tuple(
            {
                "instrument": instrument,
                "old_close": values[0],
                "new_close": values[-1],
                "score": -(values[-1] / values[0] - 1.0),
            }
            for instrument, values in sorted(by_instrument.items())
            if len(values) == 2
        )


class AbsoluteScoreModel(DataModel):
    def requirements(self):
        return (
            DataRequirement.of(
                "absolute-score",
                "reversal_features",
                fields=("score",),
                lookback=RowsLookback(1),
            ),
        )

    def compute(self, context):
        observations = context.window.observations(self.requirements()[0]).rows
        return tuple(
            {
                "instrument": row["instrument"],
                "abs_score": abs(float(row["score"])),
            }
            for row in observations
            if row["score"] is not None
        )


class ForgingModel(ReversalFeatureModel):
    def compute(self, context):
        rows = super().compute(context)
        return tuple({**row, "available_at": context.window.evaluation_time} for row in rows)
