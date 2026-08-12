from datetime import UTC, datetime
from pathlib import Path

from qlibx import OutcomeStatus, QlibxProject
from qlibx.contracts import (
    BudgetMode,
    DecisionAction,
    EveryCandidate,
    StrategyDraft,
    StrategyInvocation,
    StrategyStateUpdate,
)
from tests.test_public_daily import project as daily_project
from tests.test_public_daily import spec as daily_spec


class DirectStateStrategy:
    strategy_id = "tests.direct-state"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        prior = view.strategy_state()  # type: ignore[attr-defined]
        count = 0 if prior is None else int(prior["count"])
        return StrategyDraft(
            weights=(),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            path_dependent=True,
            state_identity=f"direct-state:{count}",
            proposed_state=StrategyStateUpdate(value={"count": count + 1}),
        )


class NonJsonStateStrategy:
    strategy_id = "tests.non-json-state"

    def requirements(self) -> tuple[object, ...]:
        return ()

    def run(self, view: object) -> StrategyDraft:
        del view
        return StrategyDraft(
            weights=(),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
            proposed_state=StrategyStateUpdate(value={"invalid": {1, 2}}),
        )


class ZeroOrderStateStrategy(DirectStateStrategy):
    strategy_id = "tests.zero-order-state"

    def trigger(self) -> EveryCandidate:
        return EveryCandidate()

    def run(self, view: object) -> StrategyDraft:
        prior = view.strategy_state()  # type: ignore[attr-defined]
        count = 0 if prior is None else int(prior["count"])
        return StrategyDraft(
            weights=(),
            budget_mode=BudgetMode.FLEXIBLE,
            target_gross=1.0,
            decision_action=DecisionAction.HOLD,
            path_dependent=True,
            state_identity=f"zero-order-state:{count}",
            proposed_state=StrategyStateUpdate(value={"count": count + 1}),
        )


def direct_project(tmp_path: Path) -> QlibxProject:
    QlibxProject.init(tmp_path, apply=True)
    return QlibxProject.open(tmp_path)


def test_direct_invoke_reads_seed_and_returns_written_strategy_state(tmp_path: Path) -> None:
    selected = direct_project(tmp_path)
    outcome = selected.invoke(
        DirectStateStrategy(),
        StrategyInvocation(
            invocation_id="direct-state-invocation",
            evaluation_time=datetime(2025, 1, 2, tzinfo=UTC),
            config_fingerprint="direct-state-v1",
            initial_strategy_state={"count": 2},
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert outcome.result.final_strategy_state == {"count": 3}
    assert outcome.result.result.strategy_state_accesses[0].strategy_id == "tests.direct-state"
    assert outcome.result.result.proposed_state == StrategyStateUpdate(value={"count": 3})


def test_non_json_strategy_state_fails_before_success_publication(tmp_path: Path) -> None:
    selected = direct_project(tmp_path)
    outcome = selected.invoke(
        NonJsonStateStrategy(),
        StrategyInvocation(
            invocation_id="non-json-state-invocation",
            evaluation_time=datetime(2025, 1, 2, tzinfo=UTC),
            config_fingerprint="non-json-state-v1",
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "MEMORY_NOT_JSON"
    assert not selected.artifacts.list_envelopes(artifact_type="strategy_result")


def test_uc_state_001_zero_order_state_crosses_run_boundary_only_through_explicit_seed(
    tmp_path: Path,
) -> None:
    selected = daily_project(tmp_path)
    first = selected.run_daily(
        ZeroOrderStateStrategy(),
        daily_spec(
            run_id="state-run-1",
            strategy_fingerprint="zero-order-state-v1",
            initial_strategy_state={"count": 4},
        ),
    )
    assert first.status is OutcomeStatus.COMPLETE
    assert first.result.executions == ()
    assert first.result.final_strategy_state == {"count": 8}
    assert first.result.checkpoint.strategy_state == {"count": 8}

    continued = selected.run_daily(
        ZeroOrderStateStrategy(),
        daily_spec(
            run_id="state-run-2",
            strategy_fingerprint="zero-order-state-v1",
            initial_strategy_state=first.result.final_strategy_state,
        ),
    )
    fresh = selected.run_daily(
        ZeroOrderStateStrategy(),
        daily_spec(
            run_id="state-run-fresh",
            strategy_fingerprint="zero-order-state-v1",
        ),
    )

    assert continued.status is fresh.status is OutcomeStatus.COMPLETE
    assert continued.result.final_strategy_state == {"count": 12}
    assert fresh.result.final_strategy_state == {"count": 4}
