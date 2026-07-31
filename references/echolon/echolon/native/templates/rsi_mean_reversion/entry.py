"""RSI mean reversion: enter LONG on oversold, SHORT on overbought."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params["rsi_period"]
        self.oversold = self.params["oversold"]
        self.overbought = self.params["overbought"]

    def generate_signal(self) -> EntrySignalOutput:
        rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        if rsi < self.oversold:
            out = EntrySignalOutput(
                signal="LONG", strength=1.0, type="mean_rev_long",
                entry_reason=f"RSI({self.rsi_period})={rsi} < {self.oversold}",
                intent=OrderIntent.ENTRY_LONG,
            )
        elif rsi > self.overbought:
            out = EntrySignalOutput(
                signal="SHORT", strength=1.0, type="mean_rev_short",
                entry_reason=f"RSI({self.rsi_period})={rsi} > {self.overbought}",
                intent=OrderIntent.ENTRY_SHORT,
            )
        else:
            out = EntrySignalOutput(
                signal="HOLD", strength=0.0, type="hold",
                entry_reason="Inside neutral zone",
            )
        self.log_entry_output(out)
        return out
