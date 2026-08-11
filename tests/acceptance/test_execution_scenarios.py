import math
from datetime import datetime

import duckdb
import pytest

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    DailySimulationSpec,
    FrozenDailyExecutionSpec,
    OperationOutcome,
    OutcomeStatus,
)
from qlibx.account import Account, StrategyMemoryStore
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    EveryCandidate,
    EveryNSessions,
    StrategyDraft,
    WeightEntry,
)
from qlibx.errors import CommitStatus, OperationError
from qlibx.flow import (
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    FrozenDecision,
)
from qlibx.flow.recovery import SIMULATION_RECOVERY_POINT_CONTRACT
from qlibx.runtime import BacktestClock
from tests.acceptance.real_dw_support import (
    RealDwProject,
    close_at,
    configured_exchange,
    configured_exchange_config,
    configured_instruments,
    initial_account,
    open_at,
    run_real_daily_flow,
)


class TargetStrategy:
    strategy_id = "tests.target"

    def __init__(self, cadence: int = 2) -> None:
        self._cadence = cadence

    def requirements(self):
        return ()

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=self._cadence)

    def run(self, view):
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


class SwitchingTargetStrategy:
    strategy_id = "tests.switching-target"

    def __init__(self) -> None:
        self.calls = 0

    def requirements(self):
        return ()

    def trigger(self) -> EveryNSessions:
        return EveryNSessions(n=2)

    def run(self, view):
        self.calls += 1
        target = "A000660" if self.calls == 1 else "A005930"
        return StrategyDraft(
            weights=(WeightEntry(instrument=target, weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
        )


class InitialMemoryTargetStrategy(TargetStrategy):
    strategy_id = "tests.initial-memory-target"

    def run(self, view):
        memory = view.memory_snapshot()
        account = view.account_snapshot()
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            feedback_cursor=str(account.feedback_cursor),
            proposed_memory={"initialized": True},
            expected_memory_version=memory.version,
        )


class RepeatedMemoryHoldStrategy:
    strategy_id = "tests.repeated-memory-hold"

    def __init__(self) -> None:
        self.calls = 0

    def requirements(self):
        return ()

    def trigger(self) -> EveryCandidate:
        return EveryCandidate()

    def run(self, view):
        self.calls += 1
        memory = view.memory_snapshot()
        account = view.account_snapshot()
        feedback = view.account_feedback()
        return StrategyDraft(
            weights=(),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.HOLD,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            feedback_cursor=str(feedback.next_cursor),
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
    assert next_decision.feedback_accesses[0].after_cursor == 2
    assert next_decision.feedback_accesses[0].next_cursor == 2
    assert next_decision.feedback_accesses[0].change_types == ()
    assert next_decision.feedback_accesses[0].fill_ids == ()
    assert next_decision.feedback_accesses[0].marked_instruments == ()
    assert next_decision.performance_accesses == ()
    assert actual.cash == pytest.approx(52_100.5)
    assert actual.nav == pytest.approx(9_985_100.5)
    assert [(item.instrument_id, item.quantity) for item in actual.holdings] == [
        ("A005930", 129)
    ]
    assert first.result.final_account.holdings() == {"A005930": 129}
    first_feedback = first.result.strategy_results[0].feedback_accesses[0]
    assert first_feedback.after_cursor == 0
    assert first_feedback.next_cursor == 0
    strategy_artifact = next(
        item
        for item in first.result.artifacts
        if item.artifact_type == "strategy_result"
        and any(
            edge.consumer_role == "actual_account_feedback"
                and edge.dependency_id.endswith("feedback:2-2")
            for edge in item.dependencies
        )
    )
    assert strategy_artifact.logical_identity.endswith("2024-01-04T06:30:00Z")

    performance = first.result.session_performance
    assert len(performance) == 4
    for record in performance:
        assert record.portfolio_return == pytest.approx(
            record.closing_nav / record.opening_nav - 1
        )
        assert record.transaction_cost_rate == pytest.approx(
            record.transaction_cost / record.opening_nav
        )
        assert record.turnover == pytest.approx(
            record.trade_value / record.opening_nav
        )
        assert record.gross_return - record.transaction_cost_rate == pytest.approx(
            record.portfolio_return
        )
    traded_session = next(
        item for item in performance if item.event_time == close_at(2024, 1, 3)
    )
    assert traded_session.source_execution_event_ids == (execution.event_id,)
    assert traded_session.trade_value == pytest.approx(execution.fills[0].trade_value)
    assert traded_session.transaction_cost == pytest.approx(
        execution.fills[0].total_cost
    )
    assert traded_session.opening_nav == pytest.approx(10_000_000)
    assert traded_session.closing_nav == pytest.approx(9_985_100.5)
    performance_artifact = next(
        item
        for item in first.result.artifacts
        if item.artifact_type == "session_performance"
        and item.logical_identity.endswith(traded_session.event_id)
    )
    assert {
        edge.consumer_role for edge in performance_artifact.dependencies
    } == {"committed_execution", "committed_mark"}
    assert all(
        item.account.version == item.account_version_after_callback
        for item in first.result.monitors
    )


def test_feedback_window_fails_before_strategy_when_limit_is_too_small(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3, 4))
    account = initial_account("bounded-feedback-account")
    memory = StrategyMemoryStore()
    memory.commit(
        strategy_id=TargetStrategy.strategy_id,
        value={"initialized": True},
        feedback_cursor=0,
        expected_version=0,
    )
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=account,
        memory=memory,
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
            feedback_entry_limit=1,
        ),
    )

    outcome = flow.run(
        TargetStrategy(),
        DailyRunRequest(
            run_id="bounded-feedback",
            config_fingerprint="bounded-feedback-v1",
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "ACCOUNT_FEEDBACK_WINDOW_EXCEEDED"
    assert outcome.errors[0].stage_path == "daily_flow.decision.feedback"
    assert outcome.errors[0].context["after_cursor"] == 0
    assert outcome.errors[0].context["next_cursor"] == 1
    assert outcome.errors[0].context["account_cursor"] == 2
    assert outcome.errors[0].context["entry_limit"] == 1
    assert outcome.errors[0].context["account_version"] == 2
    assert outcome.errors[0].context["event_name"] == "DECISION"
    assert account.feedback(0, 10).next_cursor == 2


def test_rebalance_sizes_from_current_execution_prices(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3, 4, 5))
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=initial_account("switching-target-account"),
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )

    outcome = flow.run(
        SwitchingTargetStrategy(),
        DailyRunRequest(
            run_id="switching-target",
            config_fingerprint="switching-target-v1",
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    second = outcome.result.executions[1]
    assert second.account_before.nav == pytest.approx(9_970_800)
    assert second.sizing_nav == pytest.approx(10_051_100)
    assert second.sizing_price_role == "execution_price"
    assert [(fill.instrument_id, fill.dealt_quantity) for fill in second.fills] == [
        ("A000660", 73),
        ("A005930", 131),
    ]
    final = outcome.result.final_account
    assert final.cash == pytest.approx(16_500)
    assert final.holdings() == {"A005930": 131}
    assert final.positions[0].quantity * final.positions[0].mark / final.nav == (
        pytest.approx(131 * 76_600 / 10_051_100)
    )


def test_daily_profile_rejects_impact_without_total_market_volume(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    account = initial_account("daily-impact-account")
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0, impact_rate=0.001),
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
            run_id="daily-impact-missing-volume",
            config_fingerprint="daily-impact-v1",
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "EXECUTION_MARKET_VOLUME_MISSING"
    assert outcome.errors[0].commit_status is CommitStatus.NONE
    assert account.snapshot().version == 0
    assert account.snapshot().holdings() == {}


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
    assert commit.update_kind == "INITIALIZATION"
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


def test_uc_exec_001_isolates_frozen_daily_children(
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


def test_uc_alpha_child_001_compares_real_next_close_and_open_without_rerun(
    real_dw_execution_convention_case: RealDwProject,
) -> None:
    case = real_dw_execution_convention_case
    parent, intent, artifact = _parent_decision(case, run_id="convention-parent")
    parent_checkpoint = parent.result.checkpoint
    session_close = close_at(2024, 1, 3)
    session_open = open_at(2024, 1, 3)

    def child_spec(
        *,
        run_id: str,
        account_id: str,
        timing: str,
        price_role: str,
    ) -> FrozenDailyExecutionSpec:
        return FrozenDailyExecutionSpec(
            run_id=run_id,
            parent_decision_artifact_ids=(artifact.artifact_id,),
            account=DailyAccountSeed(
                account_id=account_id,
                base_currency="KRW",
                initial_cash=10_000_000,
            ),
            instruments=configured_instruments(),
            exchange=configured_exchange_config(cost_rate=0),
            market=DailyMarketBinding(
                market_dataset_id="dw-real-execution-events",
                execution_price_role=price_role,
                valuation_price_role="valuation_price",
            ),
            execution_timing=timing,
            session_closes=(session_close,),
            session_opens=(session_open,) if timing == "next_session_open" else (),
        )

    close_child = case.project.execute_frozen_daily(
        child_spec(
            run_id="convention-close-child",
            account_id="convention-close-account",
            timing="next_session_close",
            price_role="close_execution_price",
        )
    )
    open_child = case.project.execute_frozen_daily(
        child_spec(
            run_id="convention-open-child",
            account_id="convention-open-account",
            timing="next_session_open",
            price_role="open_execution_price",
        )
    )

    assert close_child.status is open_child.status is OutcomeStatus.COMPLETE
    assert close_child.result.strategy_results == open_child.result.strategy_results == ()
    assert close_child.result.memory_commits == open_child.result.memory_commits == ()
    assert close_child.result.decision_intents == open_child.result.decision_intents == (
        intent,
    )
    close_execution = close_child.result.executions[0]
    open_execution = open_child.result.executions[0]
    assert close_execution.event_time == session_close
    assert open_execution.event_time == session_open
    assert close_execution.profile_id == "daily.next-session-close.v1"
    assert open_execution.profile_id == "daily.next-session-open.v1"
    assert close_execution.convention_id == "close-price.v1"
    assert open_execution.convention_id == "open-price.v1"
    assert close_execution.sizing_price_role == "close_execution_price"
    assert open_execution.sizing_price_role == "open_execution_price"

    expected_open, expected_close = duckdb.sql(
        f"""
        SELECT
            max(open_execution_price),
            max(close_execution_price)
        FROM read_parquet('{case.source.as_posix()}')
        WHERE ticker = 'A005930'
          AND CAST(event_time AS DATE) = DATE '2024-01-03'
        """
    ).fetchone()
    assert open_execution.fills[0].price == pytest.approx(expected_open)
    assert close_execution.fills[0].price == pytest.approx(expected_close)
    assert open_execution.fills[0].dealt_quantity == math.floor(
        10_000_000 / expected_open
    )
    assert close_execution.fills[0].dealt_quantity == math.floor(
        10_000_000 / expected_close
    )
    assert open_execution.fills[0].price != close_execution.fills[0].price
    assert open_execution.account_after.account_id == "convention-open-account"
    assert close_execution.account_after.account_id == "convention-close-account"

    for outcome, price_role in (
        (open_child, "open_execution_price"),
        (close_child, "close_execution_price"),
    ):
        execution_artifact = next(
            item
            for item in outcome.result.artifacts
            if item.artifact_type == "execution_result"
        )
        assert any(
            edge.consumer_role == "decision_intent"
            and edge.dependency_id == artifact.artifact_id
            for edge in execution_artifact.dependencies
        )
        assert any(
            edge.consumer_role == price_role
            and edge.dependency_kind == "dataset"
            for edge in execution_artifact.dependencies
        )

    reloaded_parent = next(
        item
        for item in case.project.artifacts.list_envelopes(include_failure=True)
        if item.artifact_id == artifact.artifact_id
    )
    assert reloaded_parent == artifact
    assert parent.result.checkpoint == parent_checkpoint


def test_next_open_rejects_close_available_price_before_account_mutation(
    real_dw_execution_convention_case: RealDwProject,
) -> None:
    case = real_dw_execution_convention_case
    _, _, artifact = _parent_decision(case, run_id="future-hidden-parent")
    outcome = case.project.execute_frozen_daily(
        FrozenDailyExecutionSpec(
            run_id="future-hidden-open-child",
            parent_decision_artifact_ids=(artifact.artifact_id,),
            account=DailyAccountSeed(
                account_id="future-hidden-open-account",
                base_currency="KRW",
                initial_cash=10_000_000,
            ),
            instruments=configured_instruments(),
            exchange=configured_exchange_config(cost_rate=0),
            market=DailyMarketBinding(
                market_dataset_id="dw-real-market",
                execution_price_role="execution_price",
                valuation_price_role="valuation_price",
            ),
            execution_timing="next_session_open",
            session_closes=(close_at(2024, 1, 3),),
            session_opens=(open_at(2024, 1, 3),),
        )
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "EXECUTION_SESSION_PRICE_MISSING"
    assert outcome.errors[0].commit_status is CommitStatus.NONE
    assert not any(
        item.artifact_type == "execution_result" for item in outcome.diagnostics
    )


def test_next_open_missing_binding_fails_without_execution_result(
    real_dw_execution_convention_case: RealDwProject,
) -> None:
    case = real_dw_execution_convention_case
    _, _, artifact = _parent_decision(case, run_id="missing-open-binding-parent")
    outcome = case.project.execute_frozen_daily(
        FrozenDailyExecutionSpec(
            run_id="missing-open-binding-child",
            parent_decision_artifact_ids=(artifact.artifact_id,),
            account=DailyAccountSeed(
                account_id="missing-open-binding-account",
                base_currency="KRW",
                initial_cash=10_000_000,
            ),
            instruments=configured_instruments(),
            exchange=configured_exchange_config(cost_rate=0),
            market=DailyMarketBinding(
                market_dataset_id="dw-real-execution-events",
                execution_price_role="missing_open_execution_price",
                valuation_price_role="valuation_price",
            ),
            execution_timing="next_session_open",
            session_closes=(close_at(2024, 1, 3),),
            session_opens=(open_at(2024, 1, 3),),
        )
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "REQUIREMENT_NOT_RESOLVED"
    assert outcome.errors[0].commit_status is CommitStatus.NONE
    assert not any(
        item.artifact_type == "execution_result" for item in outcome.diagnostics
    )


def test_open_profile_without_schedule_fails_before_strategy_or_state_mutation(
    real_dw_execution_convention_case: RealDwProject,
) -> None:
    case = real_dw_execution_convention_case
    strategy = SwitchingTargetStrategy()
    account = initial_account("missing-open-schedule-account")
    flow = DailyExecutionFlow(
        clock=BacktestClock(close_at(2024, 1, 2)),
        registry=case.project.registry_snapshot(),
        artifacts=case.project.artifacts,
        exchange=configured_exchange(cost_rate=0),
        account=account,
        profile=DailyExecutionProfile(
            profile_id="daily.next-session-open.v1",
            convention_id="open-price.v1",
            execution_timing="next_session_open",
            market_dataset_id="dw-real-execution-events",
            execution_price_role="open_execution_price",
            valuation_price_role="valuation_price",
        ),
    )
    outcome = flow.run(
        strategy,
        DailyRunRequest(
            run_id="missing-open-schedule",
            config_fingerprint="missing-open-schedule.v1",
            session_closes=(close_at(2024, 1, 2), close_at(2024, 1, 3)),
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "NEXT_SESSION_OPEN_SCHEDULE_REQUIRED"
    assert strategy.calls == 0
    assert account.snapshot().version == 0
    assert account.snapshot().holdings() == {}


def test_next_open_recovery_records_the_exact_pending_execution_time(
    real_dw_execution_convention_case: RealDwProject,
) -> None:
    case = real_dw_execution_convention_case
    session_open = open_at(2024, 1, 3)
    outcome = case.project.run_daily(
        TargetStrategy(),
        DailySimulationSpec(
            run_id="next-open-recovery-contract",
            strategy_fingerprint="tests.target.v1",
            account=DailyAccountSeed(
                account_id="next-open-recovery-account",
                base_currency="KRW",
                initial_cash=10_000_000,
            ),
            instruments=configured_instruments(),
            exchange=configured_exchange_config(cost_rate=0),
            market=DailyMarketBinding(
                market_dataset_id="dw-real-execution-events",
                execution_price_role="open_execution_price",
                valuation_price_role="valuation_price",
            ),
            execution_timing="next_session_open",
            session_closes=(close_at(2024, 1, 2), close_at(2024, 1, 3)),
            session_opens=(session_open,),
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    pending_times: list[datetime] = []
    for envelope in case.project.artifacts.list_envelopes():
        if envelope.artifact_type != "simulation_recovery_point":
            continue
        loaded = case.project.load_artifact(
            envelope.artifact_id,
            SIMULATION_RECOVERY_POINT_CONTRACT,
        )
        if (
            loaded.status is OutcomeStatus.COMPLETE
            and loaded.result.payload.run_id == "next-open-recovery-contract"
        ):
            pending_times.extend(
                item.execution_time
                for item in loaded.result.payload.pending_executions
            )
    assert session_open in pending_times


def test_checkpoint_round_trip_preserves_account_and_memory_state(
    real_dw_case: RealDwProject,
) -> None:
    phase_one_sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    phase_one = run_real_daily_flow(
        real_dw_case,
        run_id="resume-phase-1",
        sessions=phase_one_sessions,
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
