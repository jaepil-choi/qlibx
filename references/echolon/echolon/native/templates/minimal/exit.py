"""Minimal exit rule."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.schemas import ExitSignalOutput


class exit_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
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
            out = ExitSignalOutput(
                should_exit=False, exit_reason="Template: holding",
                position_size=abs(pos.size), bars_since_entry=self.bars_held,
            )
        self.log_exit_output(out)
        return out
