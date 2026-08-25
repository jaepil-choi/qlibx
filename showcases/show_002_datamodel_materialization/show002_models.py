from __future__ import annotations

from vqapr.authoring import DataModel, DatasetInput, DerivedRow, Output, RowsLookback


class ReversalFeatureModel(DataModel):
    def inputs(self):
        return {
            "prices": DatasetInput(
                dataset_id="price_daily",
                fields=("close",),
                lookback=RowsLookback(rows=2),
            ),
        }

    def output(self):
        return Output(semantic_fields=("old_close", "new_close", "score"))

    def compute(self, call):
        observations = call.read("prices")
        by_instrument: dict[str, list[float]] = {}
        for observation in observations:
            close = observation.values["close"]
            if close is not None:
                by_instrument.setdefault(observation.instrument_id, []).append(float(close))
        return tuple(
            DerivedRow(
                instrument_id=instrument,
                values={
                    "old_close": values[0],
                    "new_close": values[-1],
                    "score": -(values[-1] / values[0] - 1.0),
                },
            )
            for instrument, values in sorted(by_instrument.items())
            if len(values) == 2
        )


class AbsoluteScoreModel(DataModel):
    def inputs(self):
        return {
            "features": DatasetInput(
                dataset_id="reversal_features",
                fields=("score",),
                lookback=RowsLookback(rows=1),
            ),
        }

    def output(self):
        return Output(semantic_fields=("abs_score",))

    def compute(self, call):
        observations = call.read("features")
        return tuple(
            DerivedRow(
                instrument_id=observation.instrument_id,
                values={"abs_score": abs(float(observation.values["score"]))},
            )
            for observation in observations
            if observation.values["score"] is not None
        )


class ForgingModel(ReversalFeatureModel):
    def compute(self, call):
        rows = super().compute(call)
        return tuple(
            DerivedRow(
                instrument_id=row.instrument_id,
                values={**row.values, "available_at": call.evaluation_time},
            )
            for row in rows
        )
