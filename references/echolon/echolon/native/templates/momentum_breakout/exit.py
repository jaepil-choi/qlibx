"""Momentum breakout: exit on opposite-side N-bar trailing extreme.

LONG positions exit when close breaks below the trailing N-bar low; SHORT
positions exit when close breaks above the trailing N-bar high.
"""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import ExitSignalOutput


class exit_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.exit_lookback = self.params["exit_lookback"]
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
            close = self.get_current_price()
            is_long = pos.size > 0
            if is_long:
                low_n = self.get_indicator(f"lowest_low_{self.exit_lookback}", index=1)
                if close < low_n:
                    out = ExitSignalOutput(
                        should_exit=True,
                        exit_reason=f"Close {close} < {self.exit_lookback}-bar low {low_n}",
                        position_size=abs(pos.size),
                        bars_since_entry=self.bars_held,
                        intent=OrderIntent.EXIT_LONG,
                    )
                else:
                    out = ExitSignalOutput(
                        should_exit=False, exit_reason="Holding LONG",
                        position_size=abs(pos.size), bars_since_entry=self.bars_held,
                    )
            else:
                # SHORT position
                high_n = self.get_indicator(f"highest_high_{self.exit_lookback}", index=1)
                if close > high_n:
                    out = ExitSignalOutput(
                        should_exit=True,
                        exit_reason=f"Close {close} > {self.exit_lookback}-bar high {high_n}",
                        position_size=abs(pos.size),
                        bars_since_entry=self.bars_held,
                        intent=OrderIntent.EXIT_SHORT,
                    )
                else:
                    out = ExitSignalOutput(
                        should_exit=False, exit_reason="Holding SHORT",
                        position_size=abs(pos.size), bars_since_entry=self.bars_held,
                    )
        self.log_exit_output(out)
        return out
