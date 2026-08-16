from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, FrozenAgenda, FrozenRun, StrategyConfig
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.simulation import SimulationFlow
from vqapr.models.strategy_model import NoDecision, StrategyModel, StrategyModelContext
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig


@dataclass(frozen=True)
class Intent:
    occurrence_number: int
    intent_id: UUID
    strategy_id: str
    targets: tuple[object, ...]
    cash_target: Decimal
    budget: object
    source_refs: tuple[object, ...]
    account_version_seen: int
    model_state_ref: None = None


class EveryThreeOccurrences(StrategyModel):
    def on_occurrence(self, context: StrategyModelContext) -> NoDecision | Intent:
        assert not hasattr(context, "sessions")
        assert not hasattr(context, "future_occurrences")
        assert not hasattr(context, "execution_table")
        assert context.occurrence.role is OperationRole.STRATEGY_CALLBACK
        memory = dict(self.memory or {})
        count = int(memory.get("occurrence_count", 0)) + 1
        self.memory = {**memory, "occurrence_count": count}
        if count % 3:
            return NoDecision(reason="cadence")
        return Intent(
            occurrence_number=count,
            intent_id=UUID(int=count),
            strategy_id="every-three",
            targets=(),
            cash_target=Decimal(1),
            budget="fixture",
            source_refs=(),
            account_version_seen=context.account.version,
        )


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset read: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source read: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:
        raise AssertionError("NoDecision callbacks must not execute orders")


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
    valuation_agenda = FrozenAgenda("valuation", OperationRole.VALUATION, ())
    requirement = DataRequirement.of(
        "valuation", "prices", fields=("close",), lookback=RowsLookback(1)
    )
    frozen = FrozenRun(
        strategy=StrategyConfig(
            _component("strategy", ComponentKind.STRATEGY_MODEL),
            "strategy",
            OperationRole.STRATEGY_CALLBACK,
        ),
        valuation=ValuationConfig("valuation", OperationRole.VALUATION, requirement),
        constraints=ConstraintSet(()),
        strategy_agenda=strategy_agenda,
        valuation_agenda=valuation_agenda,
    )
    account = Account(AccountSnapshot(0, Decimal(1), {}), mode=AccountMode.LONG_ONLY)

    def window_for_occurrence(occurrence: OperationOccurrence) -> ModelWindow:
        return ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(requirement,),
        )

    return SimulationFlow(
        frozen,
        strategy,
        state,
        window_for_occurrence=window_for_occurrence,
        account=account,
        exchange=_Exchange(),
        constraints=(),
        marks_for_occurrence=lambda *_: {},
    )


def test_cadence_is_strategy_memory_over_explicit_current_occurrences() -> None:
    state = RunStateRepository()

    result = _flow(EveryThreeOccurrences(), state, (_occurrence(1), _occurrence(2))).run()

    assert [type(trace.result) for trace in result.occurrences] == [NoDecision, NoDecision]
    assert [trace.occurrence.occurrence_id for trace in result.occurrences] == [
        "strategy-1",
        "strategy-2",
    ]
    assert state.load_model_state(result.final_state.current_model_state_ref) == {
        "occurrence_count": 2
    }


def test_no_decision_state_continues_across_explicit_agenda_boundaries() -> None:
    state = RunStateRepository()
    _flow(EveryThreeOccurrences(), state, (_occurrence(1),)).run()

    result = _flow(EveryThreeOccurrences(), state, (_occurrence(2),)).run()

    assert isinstance(result.occurrences[0].result, NoDecision)
    assert state.load_model_state(result.final_state.current_model_state_ref) == {
        "occurrence_count": 2
    }


class TimingOverrideStrategy(EveryThreeOccurrences):
    def on_occurrence(self, context: StrategyModelContext) -> Intent:
        self.memory = {"occurrence_count": 999}
        intent = Intent(
            occurrence_number=1,
            intent_id=UUID(int=1),
            strategy_id="timing-override",
            targets=(),
            cash_target=Decimal(1),
            budget="fixture",
            source_refs=(),
            account_version_seen=context.account.version,
        )
        object.__setattr__(intent, "decision_time", context.occurrence.evaluation_time)
        return intent


def test_strategy_intent_cannot_override_flow_timing() -> None:
    state = RunStateRepository()
    strategy = TimingOverrideStrategy()

    with pytest.raises(ValueError, match="must not declare decision_time"):
        _flow(strategy, state, (_occurrence(1),)).run()

    assert state.current.current_model_state_ref is None
    assert strategy.memory is None


class FailingStrategy(EveryThreeOccurrences):
    def on_occurrence(self, context: StrategyModelContext) -> NoDecision:
        self.memory = {"occurrence_count": 999}
        raise RuntimeError("strategy bug")


def test_callback_failure_rolls_back_live_memory_and_state() -> None:
    state = RunStateRepository(initial_model_memory={"occurrence_count": 1})
    strategy = FailingStrategy()

    with pytest.raises(RuntimeError, match="strategy bug"):
        _flow(strategy, state, (_occurrence(2),)).run()

    assert state.load_model_state(state.current.current_model_state_ref) == {"occurrence_count": 1}
    assert strategy.memory == {"occurrence_count": 1}
