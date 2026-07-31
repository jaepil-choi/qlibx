"""Minimal entry rule. TODO: replace hold-forever logic with your signal."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)

    def generate_signal(self) -> EntrySignalOutput:
        # TODO: replace this with your signal logic.
        # regime is optional — TRS strategies populate it; TSMOM strategies
        # typically leave it unset. See echolon/strategy/schemas.py.
        out = EntrySignalOutput(
            signal="HOLD",
            strength=0.0,
            type="hold",
            entry_reason="Template: no entry logic yet",
        )
        self.log_entry_output(out)
        return out
