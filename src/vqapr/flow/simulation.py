"""Session-first callback Flow; economic cadence remains inside StrategyModel."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from vqapr.domain.references import ModelStateRef
from vqapr.flow.model_state import InMemoryModelStateStore
from vqapr.models.memory import ModelMemory, normalize_memory
from vqapr.models.strategy_model import NoDecision, StrategyModel, StrategyModelContext
from vqapr.portfolio.intents import PortfolioIntent
from vqapr.runtime.events import SessionEvent
from vqapr.runtime.session_stream import SessionStream


@dataclass(frozen=True, slots=True)
class SessionTrace:
    session: SessionEvent
    result: NoDecision | PortfolioIntent
    state_ref: ModelStateRef
    committed_memory: ModelMemory


@dataclass(frozen=True, slots=True)
class SimulationResult:
    sessions: tuple[SessionTrace, ...]
    final_state_ref: ModelStateRef


class SimulationFlow:
    """Deliver all current sessions and commit Strategy state after valid callbacks."""

    def __init__(
        self,
        strategy: StrategyModel,
        state_store: InMemoryModelStateStore,
        *,
        initial_state_ref: ModelStateRef | None = None,
    ) -> None:
        if not isinstance(strategy, StrategyModel):
            raise TypeError("strategy must be a StrategyModel")
        if not isinstance(state_store, InMemoryModelStateStore):
            raise TypeError("state_store must be an InMemoryModelStateStore")
        self._strategy = strategy
        self._state_store = state_store
        self._initial_state_ref = initial_state_ref

    def run(self, execution_times: Iterable[datetime]) -> SimulationResult:
        if self._initial_state_ref is None:
            self._strategy.memory = normalize_memory(self._strategy.memory)
        else:
            self._strategy.memory = self._state_store.load(self._initial_state_ref)

        stream = SessionStream.from_execution_times(
            execution_times,
            callback_time=self._strategy.callback_time(),
        )
        traces: list[SessionTrace] = []
        final_ref = self._initial_state_ref

        for event in stream:
            before = normalize_memory(self._strategy.memory)
            try:
                result = self._strategy.on_session(StrategyModelContext(session=event))
                if not isinstance(result, (NoDecision, PortfolioIntent)):
                    raise TypeError("Strategy callback must return NoDecision or an intent")
                candidate = normalize_memory(self._strategy.memory)
            except Exception:
                self._strategy.memory = before
                raise

            final_ref = self._state_store.commit(candidate)
            committed = self._state_store.load(final_ref)
            self._strategy.memory = normalize_memory(committed)
            traces.append(
                SessionTrace(
                    session=event,
                    result=result,
                    state_ref=final_ref,
                    committed_memory=committed,
                )
            )

        if final_ref is None:  # SessionStream rejects empty input; keeps this invariant explicit.
            raise RuntimeError("simulation finished without a committed Model state")
        return SimulationResult(sessions=tuple(traces), final_state_ref=final_ref)
