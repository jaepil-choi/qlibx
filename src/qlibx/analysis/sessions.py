"""Pure session-performance arithmetic over committed account evidence."""

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from qlibx.analysis.results import AnalysisError
from qlibx.models import QlibxModel
from qlibx.view import StateAccessRecord


class SessionExecutionInput(QlibxModel):
    event_id: str = Field(min_length=1)
    trade_value: float = Field(ge=0)
    transaction_cost: float = Field(ge=0)


class SessionPerformanceRequest(QlibxModel):
    event_id: str = Field(min_length=1)
    event_time: datetime
    source_mark_event_id: str = Field(min_length=1)
    source_execution_event_ids: tuple[str, ...]


class SessionPerformanceInput(QlibxModel):
    opening: StateAccessRecord
    closing: StateAccessRecord
    executions: tuple[SessionExecutionInput, ...]


class SessionPerformanceEvidence(QlibxModel):
    performance_schema_version: Literal[1] = 1
    event_id: str
    event_time: datetime
    account_id: str
    source_mark_event_id: str
    source_execution_event_ids: tuple[str, ...]
    opening_account_version: int = Field(ge=0)
    closing_account_version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    opening_nav: float = Field(ge=0)
    closing_nav: float = Field(ge=0)
    closing_cash: float
    trade_value: float = Field(ge=0)
    transaction_cost: float = Field(ge=0)
    turnover: float | None
    transaction_cost_rate: float | None
    gross_return: float | None
    portfolio_return: float | None

    @model_validator(mode="after")
    def validate_reconciliation(self) -> "SessionPerformanceEvidence":
        ratios = (
            self.turnover,
            self.transaction_cost_rate,
            self.gross_return,
            self.portfolio_return,
        )
        if self.opening_nav == 0:
            if any(value is not None for value in ratios):
                raise ValueError("zero opening NAV requires undefined return ratios")
            return self
        if any(value is None or not math.isfinite(value) for value in ratios):
            raise ValueError("positive opening NAV requires finite return ratios")
        expected_net = self.closing_nav / self.opening_nav - 1
        expected_cost = self.transaction_cost / self.opening_nav
        expected_turnover = self.trade_value / self.opening_nav
        assert self.portfolio_return is not None
        assert self.transaction_cost_rate is not None
        assert self.gross_return is not None
        assert self.turnover is not None
        if not math.isclose(self.portfolio_return, expected_net, rel_tol=0, abs_tol=1e-12):
            raise ValueError("portfolio return does not reconcile to NAV")
        if not math.isclose(
            self.transaction_cost_rate,
            expected_cost,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("transaction cost rate does not reconcile")
        if not math.isclose(self.turnover, expected_turnover, rel_tol=0, abs_tol=1e-12):
            raise ValueError("turnover does not reconcile")
        if not math.isclose(
            self.gross_return - self.transaction_cost_rate,
            self.portfolio_return,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("gross and net return do not reconcile")
        return self


def compute_session_performance(
    request: SessionPerformanceRequest,
    source: SessionPerformanceInput,
) -> SessionPerformanceEvidence:
    """Compute reconciled gross, cost and net session returns without side effects."""

    trade_value = sum(item.trade_value for item in source.executions)
    transaction_cost = sum(item.transaction_cost for item in source.executions)
    if source.opening.nav == 0:
        turnover = None
        transaction_cost_rate = None
        gross_return = None
        portfolio_return = None
    else:
        turnover = trade_value / source.opening.nav
        transaction_cost_rate = transaction_cost / source.opening.nav
        portfolio_return = source.closing.nav / source.opening.nav - 1
        gross_return = portfolio_return + transaction_cost_rate
    try:
        return SessionPerformanceEvidence(
            event_id=request.event_id,
            event_time=request.event_time,
            account_id=source.closing.account_id,
            source_mark_event_id=request.source_mark_event_id,
            source_execution_event_ids=request.source_execution_event_ids,
            opening_account_version=source.opening.version,
            closing_account_version=source.closing.version,
            feedback_cursor=source.closing.feedback_cursor,
            opening_nav=source.opening.nav,
            closing_nav=source.closing.nav,
            closing_cash=source.closing.cash,
            trade_value=trade_value,
            transaction_cost=transaction_cost,
            turnover=turnover,
            transaction_cost_rate=transaction_cost_rate,
            gross_return=gross_return,
            portfolio_return=portfolio_return,
        )
    except ValidationError as exc:
        raise AnalysisError(
            "SESSION_PERFORMANCE_NOT_RECONCILED",
            {"message": str(exc)[:500]},
        ) from exc