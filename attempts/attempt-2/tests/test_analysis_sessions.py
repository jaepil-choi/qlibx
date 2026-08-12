from datetime import UTC, datetime

import pytest

from qlibx.analysis import (
    AnalysisError,
    SessionExecutionInput,
    SessionPerformanceEvidence,
    SessionPerformanceInput,
    SessionPerformanceRequest,
    compute_session_performance,
)
from qlibx.evidence import ArtifactContract
from qlibx.view import StateAccessRecord

EVENT_TIME = datetime(2025, 1, 2, 6, 30, tzinfo=UTC)
LEGACY_JSON = (
    '{"performance_schema_version":1,"event_id":"legacy-session",'
    '"event_time":"2025-01-02T06:30:00Z","account_id":"account-1",'
    '"source_mark_event_id":"mark-1","source_execution_event_ids":["execution-1"],'
    '"opening_account_version":1,"closing_account_version":3,"feedback_cursor":2,'
    '"opening_nav":100.0,"closing_nav":101.0,"closing_cash":1.0,"trade_value":50.0,'
    '"transaction_cost":1.0,"turnover":0.5,"transaction_cost_rate":0.01,'
    '"gross_return":0.02,"portfolio_return":0.01}'
)


def state(*, version: int, nav: float, cash: float) -> StateAccessRecord:
    return StateAccessRecord(
        account_id="account-1",
        version=version,
        feedback_cursor=version,
        cash=cash,
        nav=nav,
        valuation_status="COMPLETE",
        holdings=(),
    )


def request() -> SessionPerformanceRequest:
    return SessionPerformanceRequest(
        event_id="session-1",
        event_time=EVENT_TIME,
        source_mark_event_id="mark-1",
        source_execution_event_ids=("execution-1",),
    )


def test_zero_opening_nav_leaves_all_ratios_undefined() -> None:
    result = compute_session_performance(
        request(),
        SessionPerformanceInput(
            opening=state(version=1, nav=0, cash=0),
            closing=state(version=2, nav=0, cash=0),
            executions=(),
        ),
    )

    assert (
        result.turnover,
        result.transaction_cost_rate,
        result.gross_return,
        result.portfolio_return,
    ) == (None, None, None, None)


def test_positive_opening_nav_reconciles_turnover_cost_gross_and_net() -> None:
    result = compute_session_performance(
        request(),
        SessionPerformanceInput(
            opening=state(version=1, nav=100, cash=100),
            closing=state(version=3, nav=101, cash=1),
            executions=(
                SessionExecutionInput(
                    event_id="execution-1",
                    trade_value=50,
                    transaction_cost=1,
                ),
            ),
        ),
    )

    assert result.turnover == 0.5
    assert result.transaction_cost_rate == 0.01
    assert result.portfolio_return == pytest.approx(0.01)
    assert result.gross_return == pytest.approx(0.02)
    assert result.gross_return - result.transaction_cost_rate == pytest.approx(
        result.portfolio_return
    )


def test_unreconciled_non_finite_input_is_a_typed_analysis_error() -> None:
    with pytest.raises(AnalysisError) as captured:
        compute_session_performance(
            request(),
            SessionPerformanceInput(
                opening=state(version=1, nav=100, cash=100),
                closing=state(version=2, nav=float("inf"), cash=0),
                executions=(),
            ),
        )

    assert captured.value.code == "SESSION_PERFORMANCE_NOT_RECONCILED"


def test_legacy_session_performance_json_loads_without_wire_change() -> None:
    contract = ArtifactContract(
        artifact_type="session_performance",
        artifact_schema_version=1,
        payload_model=SessionPerformanceEvidence,
    )

    loaded = contract.payload_model.model_validate_json(LEGACY_JSON)

    assert loaded.model_dump_json() == LEGACY_JSON