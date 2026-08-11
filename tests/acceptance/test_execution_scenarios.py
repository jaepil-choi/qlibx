import math
from datetime import datetime

import duckdb
import pytest

from qlibx import (
    DailyAccountSeed,
    DailyMarketBinding,
    FrozenDailyExecutionSpec,
    OperationOutcome,
    OutcomeStatus,
)
from qlibx.account import Account
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    EveryCandidate,
    EveryNSessions,
    StrategyDraft,
    StrategyStateUpdate,
    WeightEntry,
)
from qlibx.errors import CommitStatus, OperationError
from qlibx.flow import (
    DailyExecutionFlow,
    DailyExecutionProfile,
    DailyRunRequest,
    FrozenDecision,
)
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


class InitialStateTargetStrategy(TargetStrategy):
    strategy_id = "tests.initial-state-target"

    def run(self, view):
        account = view.account_snapshot()
        return StrategyDraft(
            weights=(WeightEntry(instrument="A005930", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.TARGET,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            proposed_state=StrategyStateUpdate(value={"initialized": True}),
        )


class RepeatedStateHoldStrategy:
    strategy_id = "tests.repeated-state-hold"

    def __init__(self) -> None:
        self.calls = 0

    def requirements(self):
        return ()

    def trigger(self) -> EveryCandidate:
        return EveryCandidate()

    def run(self, view):
        self.calls += 1
        account = view.account_snapshot()
        previous = view.strategy_state()
        previous_calls = previous.get("calls", 0) if isinstance(previous, dict) else 0
        return StrategyDraft(
            weights=(),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.HOLD,
            path_dependent=True,
            state_identity=f"{account.account_id}:v{account.version}",
            proposed_state=StrategyStateUpdate(value={"calls": previous_calls + 1}),
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
    assert next_decision.feedback_accesses[0].after_cursor == 0
    assert next_decision.feedback_accesses[0].next_cursor == 2
    assert next_decision.feedback_accesses[0].change_types == (
        "FillBatch",
        "MarkBatch",
    )
    assert len(next_decision.feedback_accesses[0].fill_ids) == 1
    assert next_decision.feedback_accesses[0].marked_instruments == ("A005930",)
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
            and edge.dependency_id.endswith("feedback:0-2")
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
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=account,
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
            initial_strategy_state={"initialized": True},
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


def test_uc_alpha_adaptive_001_state_is_returned_after_strategy(
    real_dw_case: RealDwProject,
) -> None:
    result = run_real_daily_flow(
        real_dw_case,
        run_id="adaptive-memory",
        account=initial_account("account-a"),
    )

    assert result.status is OutcomeStatus.COMPLETE
    assert result.result.initial_strategy_state is None
    assert result.result.final_strategy_state == {"confirmed_feedback_cursor": 2}


def test_first_decision_can_initialize_state_without_feedback(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=initial_account("initial-state-account"),
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )

    outcome = flow.run(
        InitialStateTargetStrategy(),
        DailyRunRequest(
            run_id="initial-state",
            config_fingerprint="initial-state-v1",
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert outcome.result.initial_strategy_state is None
    assert outcome.result.final_strategy_state == {"initialized": True}


def test_state_update_does_not_require_new_feedback(
    real_dw_case: RealDwProject,
) -> None:
    sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    flow = DailyExecutionFlow(
        clock=BacktestClock(sessions[0]),
        registry=real_dw_case.project.registry_snapshot(),
        artifacts=real_dw_case.project.artifacts,
        exchange=configured_exchange(cost_rate=0.0),
        account=initial_account("repeated-state-account"),
        profile=DailyExecutionProfile(
            market_dataset_id="dw-real-market",
            execution_price_role="execution_price",
            valuation_price_role="valuation_price",
        ),
    )

    outcome = flow.run(
        RepeatedStateHoldStrategy(),
        DailyRunRequest(
            run_id="repeated-state",
            config_fingerprint="repeated-state-v1",
            session_closes=sessions,
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert outcome.result.initial_strategy_state is None
    assert outcome.result.final_strategy_state == {"calls": 2}


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
    assert normal.result.final_strategy_state is partial.result.final_strategy_state is None
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
    assert close_child.result.final_strategy_state is None
    assert open_child.result.final_strategy_state is None
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



def test_explicit_seed_continues_account_and_strategy_state(
    real_dw_case: RealDwProject,
) -> None:
    phase_one_sessions = tuple(close_at(2024, 1, day) for day in (2, 3))
    phase_one = run_real_daily_flow(
        real_dw_case,
        run_id="resume-phase-1",
        sessions=phase_one_sessions,
    )
    restored_account = Account.from_checkpoint(phase_one.result.checkpoint.account_checkpoint)
    continued_state = {
        "confirmed_feedback_cursor": phase_one.result.final_account.feedback_cursor
    }
    phase_two_sessions = tuple(close_at(2024, 1, day) for day in (4, 5))
    phase_two = run_real_daily_flow(
        real_dw_case,
        run_id="resume-phase-2",
        sessions=phase_two_sessions,
        account=restored_account,
        initial_strategy_state=continued_state,
    )
    uninterrupted = run_real_daily_flow(
        real_dw_case,
        run_id="resume-uninterrupted",
    )

    assert phase_one.status is OutcomeStatus.COMPLETE
    assert phase_two.status is OutcomeStatus.COMPLETE
    assert phase_one.result.final_strategy_state is None
    assert phase_two.result.initial_strategy_state == continued_state
    assert phase_two.result.final_strategy_state == continued_state
    assert phase_two.result.final_account == uninterrupted.result.final_account
