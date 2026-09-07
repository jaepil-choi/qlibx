from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintCall,
    ConstraintFinding,
    Hold,
    Rebalance,
    StrategyModel,
)
from vqapr.calls import StrategyModelContext
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence, OperationRole
from vqapr.domain.values import LocalInstantDeclaration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.flow.run import ConstraintSet, StrategyConfig
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.simulation import SimulationFlow
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.portfolio.intents import EconomicPortfolioIntent, IntentSourceRef

_BUDGET = Budget(
    PortfolioDirection.LONG_ONLY, Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")
)
_SOURCE = IntentSourceRef("strategy-source", "0" * 64)


def _state(*, memory: object = None) -> RunStateRepository:
    return RunStateRepository(
        initial_account=AccountState(AccountSnapshot(0, Decimal(1), {})),
        initial_model_memory=memory,
    )


class EveryThreeOccurrences(StrategyModel):
    def decide(self, context: StrategyModelContext) -> Hold | EconomicPortfolioIntent:
        assert not hasattr(context, "sessions")
        assert not hasattr(context, "future_occurrences")
        assert not hasattr(context, "execution_table")
        assert context.occurrence.role is OperationRole.STRATEGY_CALLBACK
        memory = dict(self.memory or {})
        count = int(memory.get("occurrence_count", 0)) + 1
        self.memory = {**memory, "occurrence_count": count}
        if count % 3:
            return Hold(reason="cadence")
        return Rebalance(
            target_weights={},
            cash_weight=Decimal(1),
            budget=_BUDGET,
        )


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset read: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source read: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:
        raise AssertionError("Hold callbacks must not execute orders")


class _Constraint(Constraint):
    @property
    def constraint_id(self) -> str:
        return "constraint"

    def requirements(self) -> tuple[DataRequirement, ...]:
        return ()

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        return ConstraintBounds(
            lower_weights={instrument: Decimal("0") for instrument in call.instruments},
            upper_weights={instrument: Decimal("1") for instrument in call.instruments},
        )

    def monitor(self, call, account, bounds) -> ConstraintFinding:
        return ConstraintFinding(
            passed=True, measured=Decimal("0"), bound=Decimal("1"), excess=Decimal("0"), details={}
        )


def _occurrence(number: int) -> OperationOccurrence:
    return OperationOccurrence(
        f"strategy-{number}",
        OperationRole.STRATEGY_CALLBACK,
        LocalInstantDeclaration(date(2024, 3, number + 4), time(4, 0), "Asia/Seoul", 0, "+09:00"),
    )


def _component(raw_id: str, kind: ComponentKind) -> ComponentRef:
    return ComponentRef.of(
        raw_id,
        kind,
        Path("component.py"),
        "Component",
        fingerprint="0" * 64,
    )


def _flow(
    strategy: StrategyModel,
    state: RunStateRepository,
    occurrences: tuple[OperationOccurrence, ...],
) -> SimulationFlow:
    strategy_agenda = FrozenAgenda("strategy", OperationRole.STRATEGY_CALLBACK, occurrences)
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(1))
    frozen = FrozenRun(
        run_id="test",
        strategies=(
            FrozenStrategy(
                config=StrategyConfig(
                    _component("strategy", ComponentKind.STRATEGY_MODEL),
                    "strategy",
                    OperationRole.STRATEGY_CALLBACK,
                ),
                constraints=ConstraintSet((_component("constraint", ComponentKind.CONSTRAINT),)),
                agenda=strategy_agenda,
            ),
        ),
        start=occurrences[0].evaluation_time,
        end=occurrences[-1].evaluation_time,
        initial_account_snapshot=AccountSnapshot(0, Decimal(1), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A",),
    )
    account = Account(mode=AccountMode.LONG_ONLY)

    def window_for_occurrence(occurrence: OperationOccurrence) -> ModelWindow:
        return ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(requirement,),
            consumer_id="test-consumer",
        )

    return SimulationFlow(
        frozen,
        strategy,
        state,
        strategy_window_for_occurrence=window_for_occurrence,
        constraint_window_for_occurrence=window_for_occurrence,
        account=account,
        exchange=_Exchange(),
        constraints=(_Constraint(),),
    )


def test_cadence_is_strategy_memory_over_explicit_current_occurrences() -> None:
    state = _state()

    result = _flow(EveryThreeOccurrences(), state, (_occurrence(1), _occurrence(2))).run()

    assert [type(trace.result) for trace in result.occurrences] == [Hold, Hold]
    assert [trace.occurrence.occurrence_id for trace in result.occurrences] == [
        "strategy-1",
        "strategy-2",
    ]
    assert state.load_model_state(result.final_state.current_model_state_ref) == {
        "occurrence_count": 2
    }


def test_no_decision_state_continues_across_explicit_agenda_boundaries() -> None:
    state = _state(memory={"occurrence_count": 1})
    result = _flow(EveryThreeOccurrences(), state, (_occurrence(2),)).run()

    assert isinstance(result.occurrences[0].result, Hold)
    assert state.load_model_state(result.final_state.current_model_state_ref) == {
        "occurrence_count": 2
    }


class TimingOverrideStrategy(EveryThreeOccurrences):
    def decide(self, context: StrategyModelContext) -> Rebalance:
        self.memory = {"occurrence_count": 999}
        return Rebalance(
            target_weights={},
            cash_weight=Decimal(1),
            budget=_BUDGET,
        )


def test_strategy_intent_requires_a_flow_owned_execution_target() -> None:
    state = _state()
    strategy = TimingOverrideStrategy()
    before_ref = state.current.current_model_state_ref

    with pytest.raises(ValueError, match="requires frozen execution input"):
        _flow(strategy, state, (_occurrence(1),)).run()

    assert state.current.current_model_state_ref == before_ref
    assert strategy.memory is None


class FailingStrategy(EveryThreeOccurrences):
    def decide(self, context: StrategyModelContext) -> Hold:
        self.memory = {"occurrence_count": 999}
        raise RuntimeError("strategy bug")


def test_callback_failure_rolls_back_live_memory_and_state() -> None:
    state = _state(memory={"occurrence_count": 1})
    strategy = FailingStrategy()

    with pytest.raises(RuntimeError, match="strategy bug"):
        _flow(strategy, state, (_occurrence(2),)).run()

    assert state.load_model_state(state.current.current_model_state_ref) == {"occurrence_count": 1}
    assert strategy.memory == {"occurrence_count": 1}
