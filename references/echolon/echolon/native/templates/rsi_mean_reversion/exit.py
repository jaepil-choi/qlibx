"""RSI mean reversion: LONG exits on overbought, SHORT exits on oversold."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import ExitSignalOutput


class exit_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params["rsi_period"]
        self.oversold = self.params["oversold"]
        self.overbought = self.params["overbought"]
        self.bars_held = 0

    def should_exit(self) -> ExitSignalOutput:
        pos = self.portfolio.get_position()
        if not pos or pos.size == 0:
            self.bars_held = 0
            out = ExitSignalOutput(
                should_exit=False, exit_reason="No position",
                position_size=0.0, bars_since_entry=0,
            )
        else:
            self.bars_held += 1
            rsi = self.get_indicator(f"rsi_{self.rsi_period}")
            is_long = pos.size > 0
            if is_long and rsi > self.overbought:
                out = ExitSignalOutput(
                    should_exit=True,
                    exit_reason=f"RSI={rsi} > {self.overbought}",
                    position_size=abs(pos.size),
                    bars_since_entry=self.bars_held,
                    intent=OrderIntent.EXIT_LONG,
                )
            elif not is_long and rsi < self.oversold:
                out = ExitSignalOutput(
                    should_exit=True,
                    exit_reason=f"RSI={rsi} < {self.oversold}",
                    position_size=abs(pos.size),
                    bars_since_entry=self.bars_held,
                    intent=OrderIntent.EXIT_SHORT,
                )
            else:
                out = ExitSignalOutput(
                    should_exit=False,
                    exit_reason="Holding LONG" if is_long else "Holding SHORT",
                    position_size=abs(pos.size), bars_since_entry=self.bars_held,
                )
        self.log_exit_output(out)
        return out
