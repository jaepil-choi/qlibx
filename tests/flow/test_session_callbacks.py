from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from vqapr.flow.model_state import InMemoryModelStateStore
from vqapr.flow.simulation import SimulationFlow
from vqapr.models.strategy_model import NoDecision, StrategyModel, StrategyModelContext
from vqapr.runtime.events import LocalEvaluationTime

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Intent:
    session_number: int
    intent_id: UUID
    strategy_id: str
    decision_time: datetime
    effective_after: datetime
    targets: tuple[object, ...]
    cash_target: Decimal
    budget: object
    source_refs: tuple[object, ...]
    account_version_seen: int
    model_state_ref: None = None


class EveryThreeSessions(StrategyModel):
    def callback_time(self) -> LocalEvaluationTime:
        return LocalEvaluationTime(time(4, 0), "Asia/Seoul")

    def on_session(self, context: StrategyModelContext) -> NoDecision | Intent:
        assert not hasattr(context, "future_sessions")
        assert not hasattr(context, "execution_table")
        assert not hasattr(context, "calendar")
        memory = dict(self.memory or {})
        count = int(memory.get("session_count", 0)) + 1
        self.memory = {**memory, "session_count": count}
        if count % 3:
            return NoDecision(reason="cadence")
        return Intent(
            session_number=count,
            intent_id=UUID(int=count),
            strategy_id="every-three",
            decision_time=context.session.evaluation_time,
            effective_after=context.session.execution_time,
            targets=(),
            cash_target=Decimal(1),
            budget="fixture",
            source_refs=(),
            account_version_seen=0,
        )


def _execution_times(*days: int) -> tuple[datetime, ...]:
    return tuple(datetime(2024, 3, day, 15, 30, tzinfo=KST) for day in days)


def test_every_n_is_strategy_memory_not_a_flow_schedule() -> None:
    state_store = InMemoryModelStateStore()
    result = SimulationFlow(EveryThreeSessions(), state_store).run(_execution_times(5, 6, 7))

    assert [type(trace.result) for trace in result.sessions] == [
        NoDecision,
        NoDecision,
        Intent,
    ]
    assert [trace.committed_memory["session_count"] for trace in result.sessions] == [1, 2, 3]
    assert state_store.load(result.final_state_ref) == {"session_count": 3}


def test_no_decision_state_continues_across_an_explicit_run_boundary() -> None:
    state_store = InMemoryModelStateStore()
    first = SimulationFlow(EveryThreeSessions(), state_store).run(_execution_times(5, 6))

    second = SimulationFlow(
        EveryThreeSessions(),
        state_store,
        initial_state_ref=first.final_state_ref,
    ).run(_execution_times(7))

    assert isinstance(second.sessions[0].result, Intent)
    assert second.sessions[0].result.session_number == 3
    assert second.sessions[0].committed_memory == {"session_count": 3}


class FailingStrategy(EveryThreeSessions):
    def on_session(self, context: StrategyModelContext) -> NoDecision | Intent:
        self.memory = {"session_count": 999}
        raise RuntimeError("strategy bug")


def test_failed_callback_keeps_previous_committed_state() -> None:
    state_store = InMemoryModelStateStore()
    first = SimulationFlow(EveryThreeSessions(), state_store).run(_execution_times(5))
    strategy = FailingStrategy()
    flow = SimulationFlow(strategy, state_store, initial_state_ref=first.final_state_ref)

    with pytest.raises(RuntimeError, match="strategy bug"):
        flow.run(_execution_times(6))

    assert state_store.load(first.final_state_ref) == {"session_count": 1}
    assert strategy.memory == {"session_count": 1}


class InvalidStrategy(EveryThreeSessions):
    def on_session(self, context: StrategyModelContext):
        self.memory = {"session_count": 999}
        return None


def test_invalid_callback_result_is_not_committed() -> None:
    state_store = InMemoryModelStateStore()
    strategy = InvalidStrategy()

    with pytest.raises(TypeError, match="NoDecision or an intent"):
        SimulationFlow(strategy, state_store).run(_execution_times(5))

    assert state_store.commit_count == 0
    assert strategy.memory is None


class WrongTypeStrategy(EveryThreeSessions):
    def on_session(self, context: StrategyModelContext):
        self.memory = {"session_count": 999}
        return "not-an-intent"


def test_non_intent_callback_result_is_not_committed() -> None:
    state_store = InMemoryModelStateStore()
    strategy = WrongTypeStrategy()

    with pytest.raises(TypeError, match="NoDecision or an intent"):
        SimulationFlow(strategy, state_store).run(_execution_times(5))

    assert state_store.commit_count == 0
    assert strategy.memory is None
