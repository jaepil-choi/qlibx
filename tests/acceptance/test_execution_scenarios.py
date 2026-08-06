from datetime import datetime

import pytest

from qlibx import OperationOutcome, OutcomeStatus
from qlibx.account import Account, StrategyMemoryStore
from qlibx.errors import CommitStatus, OperationError
from qlibx.flow import (
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    FrozenDecision,
)
from qlibx.kernel import BacktestClock
from qlibx.operations import (
    BudgetMode,
    DecisionAction,
    StrategyDraft,
    WeightEntry,
)
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    configured_exchange,
    initial_account,
    run_real_daily_flow,
)


class TargetStrategy:
    strategy_id = "tests.target"

    def requirements(self):
        return ()

    def run(self, view):
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


class InitialMemoryTargetStrategy(TargetStrategy):
    strategy_id = "tests.initial-memory-target"

    def run(self, view):
        memory = view.memory_snapshot()
        view.account_snapshot()
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            proposed_memory={"initialized": True},
            expected_memory_version=memory.version,
        )


class RepeatedMemoryHoldStrategy:
    strategy_id = "tests.repeated-memory-hold"

    def __init__(self) -> None:
        self.calls = 0

    def requirements(self):
        return ()

    def run(self, view):
        self.calls += 1
        memory = view.memory_snapshot()
        view.account_snapshot()
        return StrategyDraft(
            weights=(),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.HOLD,
            proposed_memory={"calls": self.calls},
            expected_memory_version=memory.version,
        )


class FailExecutionResultArtifacts:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def publish_model(self, **kwargs):
        if kwargs["artifact_type"] != "execution_result":
            return self._delegate.publish_model(**kwargs)
        error = OperationError(
            operation="artifact.publish",
            stage_path="artifact.publish.injected_failure",
            error_code="INJECTED_EXECUTION_PUBLICATION_FAILURE",
            idempotency_identity=kwargs["logical_identity"],
            error_id="error-injected-execution-publication",
        )
        return OperationOutcome(status=OutcomeStatus.FAILED, errors=(error,))


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
    assert commit.update_kind == "FEEDBACK_UPDATE"
    assert commit.value == {"confirmed_feedback_cursor": 2}
    assert memory.snapshot("acceptance.actual-state-momentum").feedback_cursor == 2


def test_first_decision_can_initialize_memory_without_feedback(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    memory = StrategyMemoryStore()
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=initial_account("initial-memory-account"),
        memory=memory,
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )

    outcome = flow.run(
        InitialMemoryTargetStrategy(),
        DailyRunRequest(
            run_id="initial-memory",
            config_fingerprint="initial-memory-v1",
            decision_times=(sessions[0],),
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    commit = outcome.result.memory_commits[0]
    assert commit.previous_version == 0
    assert commit.version == 1
    assert commit.feedback_cursor == 0
    assert commit.update_kind == "INITIALIZATION"
    assert commit.value == {"initialized": True}
    artifact = next(
        item
        for item in outcome.result.artifacts
        if item.artifact_type == "memory_commit"
    )
    assert any(
        edge.consumer_role == "initial_actual_state" for edge in artifact.dependencies
    )
    assert memory.snapshot(InitialMemoryTargetStrategy.strategy_id).feedback_cursor == 0


def test_memory_update_after_initialization_still_requires_new_feedback(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    memory = StrategyMemoryStore()
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=initial_account("repeated-memory-account"),
        memory=memory,
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )

    outcome = flow.run(
        RepeatedMemoryHoldStrategy(),
        DailyRunRequest(
            run_id="repeated-memory",
            config_fingerprint="repeated-memory-v1",
            decision_times=sessions,
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "MEMORY_FEEDBACK_NOT_ADVANCED"
    assert outcome.errors[0].commit_status is CommitStatus.NONE
    assert memory.snapshot(RepeatedMemoryHoldStrategy.strategy_id).version == 1
    assert memory.snapshot(RepeatedMemoryHoldStrategy.strategy_id).value == {"calls": 1}


def test_post_fill_publication_failure_reports_committed_account(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    account = initial_account("post-commit-failure-account")
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=FailExecutionResultArtifacts(real_dw_case.project.artifacts),
        exchange=configured_exchange(cost_rate=0.0),
        account=account,
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )

    outcome = flow.run(
        TargetStrategy(),
        DailyRunRequest(
            run_id="post-commit-publication-failure",
            config_fingerprint="post-commit-v1",
            decision_times=(sessions[0],),
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    error = outcome.errors[0]
    assert error.error_code == "ARTIFACT_PUBLICATION_FAILED"
    assert error.commit_status is CommitStatus.COMMITTED
    assert error.context["account_version"] == 1
    committed = error.context["authoritative_commits"]
    assert len(committed) == 1
    assert committed[0]["event_name"] == "EXECUTION"
    assert datetime.fromisoformat(committed[0]["event_time"]) == sessions[1]
    assert committed[0]["authority"] == "account"
    assert committed[0]["event_id"].endswith(":fill")
    assert committed[0]["version"] == 1
    assert error.context["publication_errors"][0]["error_code"] == (
        "INJECTED_EXECUTION_PUBLICATION_FAILURE"
    )
    assert account.snapshot().version == 1
    assert account.snapshot().holdings() == {"A005930": 129}


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
