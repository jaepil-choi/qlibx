"""Minimal working strategy. Edit _execute_bar to customize."""

from echolon.strategy.base import BaseStrategy


class strategy_main(BaseStrategy):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)

    def _execute_bar(self) -> None:
        risk_out = self.risk_manager.can_trade()
        if not risk_out.trading_allowed:
            return
        if self.has_position() and not self.has_pending_orders():
            exit_out = self.exit_rule.should_exit()
            if exit_out.should_exit and exit_out.intent is not None:
                self.exit(exit_out.intent)
                return
        if not self.has_position() and not self.has_pending_orders():
            entry_out = self.entry_rule.generate_signal()
            if entry_out.signal != "HOLD" and entry_out.intent is not None:
                sizer_out = self.position_sizer.calculate_size(entry_out)
                if sizer_out.calculated_size > 0:
                    self.entry(entry_out.intent, sizer_out.calculated_size)
