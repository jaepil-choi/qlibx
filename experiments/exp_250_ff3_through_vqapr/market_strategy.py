"""The market leg for RMRF: hold the KOSPI index, fully invested, from June 2018 on.

The index level is registered as an execution table of its own (instrument `KOSPI`, kind
`index`), so this book's NAV return is the KOSPI index return and nothing else.
"""

from vqapr import authoring as va


class FfMarket(va.StrategyModel):
    """Buy the KOSPI index once and keep holding it."""

    def inputs(self):
        return {
            "ix": va.DatasetInput(
                dataset_id="ff-kospi",
                fields=("close",),
                lookback=va.CalendarLookback(days=10, timezone="Asia/Seoul"),
            )
        }

    def decide(self, call):
        level = call.read("ix", "close").current()
        if level.get("KOSPI") is None:
            return va.Hold(reason="no KOSPI level at the newest instant")
        return va.Rebalance.of(long={"KOSPI": 1}, invested=1)
