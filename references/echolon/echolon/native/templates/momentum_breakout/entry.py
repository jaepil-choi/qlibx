"""Momentum breakout: enter LONG on N-bar high, SHORT on N-bar low.

This example is paradigm-blind: ``regime`` on EntrySignalOutput is left unset
(see ``echolon/strategy/schemas.py``). Strategies that want regime-conditional
behavior register a classifier via ``echolon.indicators.registry`` and read it
through ``get_market_regime()``.
"""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.lookback = self.params["lookback"]

    def generate_signal(self) -> EntrySignalOutput:
        # Read the prior bar's channel (index=1) so today's close is compared
        # against high/low calculated up to and including yesterday — avoids
        # the off-by-one of using the current bar in its own breakout check.
        close = self.get_current_price()
        high_n = self.get_indicator(f"highest_high_{self.lookback}", index=1)
        low_n = self.get_indicator(f"lowest_low_{self.lookback}", index=1)
        if close > high_n:
            out = EntrySignalOutput(
                signal="LONG", strength=1.0, type="breakout_long",
                entry_reason=f"Close {close} > {self.lookback}-bar high {high_n}",
                intent=OrderIntent.ENTRY_LONG,
            )
        elif close < low_n:
            out = EntrySignalOutput(
                signal="SHORT", strength=1.0, type="breakout_short",
                entry_reason=f"Close {close} < {self.lookback}-bar low {low_n}",
                intent=OrderIntent.ENTRY_SHORT,
            )
        else:
            out = EntrySignalOutput(
                signal="HOLD", strength=0.0, type="hold",
                entry_reason="No breakout",
            )
        self.log_entry_output(out)
        return out
