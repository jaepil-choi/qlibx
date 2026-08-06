import pytest

from qlibx import OutcomeStatus
from qlibx.account import Account, StrategyMemoryStore
from qlibx.flow import (
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    FrozenDecision,
)
from qlibx.kernel import BacktestClock
from qlibx.operations import DecisionAction
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    configured_exchange,
    initial_account,
    run_real_daily_flow,
)


def _parent_decision(case: RealDwProject, *, run_id: str):
    outcome = run_real_daily_flow(case, run_id=run_id)
    intent = outcome.result.decision_intents[0]
    artifact = next(
        item
        for item in outcome.result.artifacts
        if item.artifact_type == "decision_intent"
    )
    return outcome, intent, artifact


def test_uc_closed_loop_001_and_uc_exec_002_real_dw_daily(
    real_dw_case: RealDwProject,
) -> None:
    first = run_real_daily_flow(real_dw_case, run_id="closed-loop-repeat")
    second = run_real_daily_flow(real_dw_case, run_id="closed-loop-repeat")

    assert first.status is OutcomeStatus.COMPLETE
    assert second.status is OutcomeStatus.COMPLETE
    assert first.result.checkpoint.account == second.result.checkpoint.account
    assert first.result.executions == second.result.executions
    assert len(first.result.decision_intents) == 1
    assert first.result.decision_intents[0].targets[0].instrument_id == "A005930"
    execution = first.result.executions[0]
    assert execution.event_time == close_at(2024, 1, 3)
    assert execution.fills[0].price == 77_000
    assert execution.fills[0].dealt_quantity == 129
    assert execution.fills[0].total_cost == pytest.approx(14_899.5)
    assert "intraday path and market impact are not modelled" in execution.limitations

    next_decision = first.result.strategy_results[1]
    actual = next_decision.state_accesses[0]
    assert next_decision.decision_action is DecisionAction.HOLD
    assert actual.version == 2
    assert actual.feedback_cursor == 2
    assert actual.cash == pytest.approx(52_100.5)
    assert actual.nav == pytest.approx(9_985_100.5)
    assert [(item.instrument_id, item.quantity) for item in actual.holdings] == [
        ("A005930", 129)
    ]
    assert first.result.final_account.holdings() == {"A005930": 129}
    assert all(
        item.account.version == item.account_version_after_callback
        for item in first.result.monitors
    )


def test_uc_alpha_adaptive_001_memory_commits_only_after_feedback(
    real_dw_case: RealDwProject,
) -> None:
    memory = StrategyMemoryStore()
    result = run_real_daily_flow(
        real_dw_case,
        run_id="adaptive-memory",
        account=initial_account("account-a"),
        memory=memory,
    )

    assert result.status is OutcomeStatus.COMPLETE
    assert len(result.result.memory_commits) == 1
    commit = result.result.memory_commits[0]
    assert commit.previous_version == 0
    assert commit.version == 1
    assert commit.feedback_cursor == 2
    assert commit.value == {"confirmed_feedback_cursor": 2}
    assert memory.snapshot("acceptance.actual-state-momentum").feedback_cursor == 2


def test_uc_exec_001_and_uc_alpha_child_001_isolate_frozen_daily_children(
    real_dw_case: RealDwProject,
) -> None:
    parent, intent, artifact = _parent_decision(real_dw_case, run_id="daily-child-parent")
    parent_checkpoint = parent.result.checkpoint
    child_session = (close_at(2024, 1, 3),)

    def execute_child(run_id: str, participation_rate: float | None):
        flow = DailyExecutionFlow(
            clock=BacktestClock(intent.decision_time),
            registry=real_dw_case.project.registry_snapshot(),
            artifacts=real_dw_case.project.artifacts,
            exchange=configured_exchange(participation_rate=participation_rate),
            account=initial_account(run_id),
            profile=DailyExecutionProfile(
                profile_id=f"{run_id}.profile",
                market_dataset_id="dw-real-market",
                execution_price_role="execution_price",
                valuation_price_role="valuation_price",
                volume_role="trade_volume" if participation_rate is not None else None,
            ),
        )
        return flow.execute_frozen(
            (FrozenDecision(intent=intent, artifact=artifact),),
            DailyRunRequest(
                run_id=run_id,
                config_fingerprint=f"{run_id}.config",
                decision_times=(),
                session_closes=child_session,
            ),
        )

    normal = execute_child("daily-child-normal", None)
    partial = execute_child("daily-child-partial", 0.000001)

    assert normal.result.final_account.holdings() == {"A005930": 129}
    assert partial.result.final_account.holdings() == {"A005930": 21}
    assert partial.result.executions[0].diagnostics[0].reasons == (
        "VOLUME_LIMIT",
        "LOT_ROUNDING",
    )
    assert parent.result.checkpoint == parent_checkpoint
    assert normal.result.strategy_results == partial.result.strategy_results == ()
    assert normal.result.memory_commits == partial.result.memory_commits == ()
    assert all(
        edge.dependency_id == artifact.artifact_id
        for outcome in (normal, partial)
        for envelope in outcome.result.artifacts
        if envelope.artifact_type == "execution_result"
        for edge in envelope.dependencies
        if edge.consumer_role == "decision_intent"
    )


def test_gap_recovery_001_account_and_memory_checkpoint_resume(
    real_dw_case: RealDwProject,
) -> None:
    phase_one_sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    phase_one = run_real_daily_flow(
        real_dw_case,
        run_id="resume-phase-1",
        sessions=phase_one_sessions,
        decision_times=(phase_one_sessions[0],),
    )
    restored_account = Account.from_checkpoint(phase_one.result.checkpoint.account_checkpoint)
    restored_memory = StrategyMemoryStore.from_checkpoint(
        phase_one.result.checkpoint.memory_snapshots
    )
    phase_two_sessions = tuple(close_at(2024, 1, day) for day in (4, 5))
    phase_two = run_real_daily_flow(
        real_dw_case,
        run_id="resume-phase-2",
        sessions=phase_two_sessions,
        decision_times=(phase_two_sessions[0],),
        account=restored_account,
        memory=restored_memory,
    )
    uninterrupted = run_real_daily_flow(
        real_dw_case,
        run_id="resume-uninterrupted",
    )

    assert phase_one.status is OutcomeStatus.COMPLETE
    assert phase_two.status is OutcomeStatus.COMPLETE
    assert phase_two.result.strategy_results[0].state_accesses[0].version == 2
    assert phase_two.result.memory_commits[0].feedback_cursor == 2
    assert phase_two.result.final_account == uninterrupted.result.final_account
