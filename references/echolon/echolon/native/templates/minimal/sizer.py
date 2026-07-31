"""Minimal sizer."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.schemas import EntrySignalOutput, SizerOutput


class position_sizer(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        size = self.validate_and_convert_position_size(1.0)
        out = SizerOutput(
            calculated_size=size, signal_direction=signal_data.signal,
            sizing_reason="Template: fixed 1 lot", raw_size=1.0,
        )
        self.log_sizer_output(out)
        return out
