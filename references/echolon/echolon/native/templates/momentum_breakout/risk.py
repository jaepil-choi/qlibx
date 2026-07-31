"""Minimal risk manager."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.schemas import RiskOutput


class risk_manager(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)

    def can_trade(self) -> RiskOutput:
        out = RiskOutput(trading_allowed=True, risk_reason="Template: always allow")
        self.log_risk_output(out)
        return out
