from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.authoring import (
    Hold,
    Rebalance,
    StrategyModel,
)
from vqapr.component.reference import ComponentRef
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.account import Account, AccountMode, AccountSnapshot, AccountState
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.domain.intent import Budget, EconomicPortfolioIntent, IntentSourceRef, PortfolioDirection
from vqapr.domain.schedule import OperationOccurrence
from vqapr.domain.wiring import Role
from vqapr.flow.declaration.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.flow.engine.run_state import RunStateRepository
from vqapr.flow.run.calls import StrategyModelContext
from vqapr.flow.run.loop import RunLoop, strategy_loop
from vqapr.project.run import ComplianceSet, StrategyConfig

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


def _occurrence(number: int) -> OperationOccurrence:
    return OperationOccurrence(
        f"strategy-{number}",
        LocalInstantDeclaration(date(2024, 3, number + 4), time(4, 0), "Asia/Seoul", 0, "+09:00"),
    )


def _component(raw_id: str, kind: Role) -> ComponentRef:
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
) -> RunLoop:
    strategy_agenda = FrozenAgenda("strategy", occurrences)
    requirement = DataRequirement.of('prices', 'close', lookback=RowsLookback(1))
    frozen = FrozenRun(
        run_id="test",
        strategy=FrozenStrategy(
                config=StrategyConfig(
                    _component("strategy", Role.STRATEGY_MODEL),
                    "strategy",
                ),
                compliance=ComplianceSet(()),
                agenda=strategy_agenda,
            ),
        start=occurrences[0].evaluation_time,
        end=occurrences[-1].evaluation_time,
        initial_account_snapshot=AccountSnapshot(0, Decimal(1), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A",),
        writes="test-weights",
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

    return strategy_loop(
        frozen,
        strategy,
        state,
        strategy_window_for_occurrence=window_for_occurrence,
        account=account,
        exchange=_Exchange(),
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


class DocumentedMemoryExample(StrategyModel):
    """`memory-and-payload.md`'s example, verbatim: it assumes `self.memory` is a mapping."""

    def decide(self, call: StrategyModelContext) -> Hold:
        seen = self.memory.setdefault("sessions", 0)  # type: ignore[union-attr]
        self.memory["sessions"] = seen + 1  # type: ignore[index]
        return Hold(reason="counting sessions")


def test_the_documented_memory_example_runs_on_the_first_callback() -> None:
    """An undeclared opening memory is `{}`, not `None` (`docs/issues/089`).

    The reference promises "restored before every `decide()`" and shows `setdefault` unguarded;
    with `None` as the opening memory that example raised `AttributeError` on session one of
    every run. The frozen layer's default is what the run state is seeded from, so the test seeds
    it the way `orchestration` does.
    """
    layer = FrozenStrategy(
        config=StrategyConfig(_component("strategy", Role.STRATEGY_MODEL), "strategy"),
        compliance=ComplianceSet(()),
        agenda=FrozenAgenda("strategy", (_occurrence(1),)),
    )
    assert layer.initial_model_memory == {}
    state = _state(memory=layer.initial_model_memory)
    strategy = DocumentedMemoryExample()

    _flow(strategy, state, (_occurrence(1), _occurrence(2))).run()

    assert strategy.memory == {"sessions": 2}
    assert state.load_model_state(state.current.current_model_state_ref) == {"sessions": 2}


def test_strategy_intent_requires_a_flow_owned_execution_target() -> None:
    state = _state()
    strategy = TimingOverrideStrategy()
    before_ref = state.current.current_model_state_ref

    with pytest.raises(ValueError, match="requires frozen execution dataset"):
        _flow(strategy, state, (_occurrence(1),)).run()

    assert state.current.current_model_state_ref == before_ref
    # The opening memory, restored before the callback and nothing more: what the callback wrote
    # did not survive the refusal. `{}` since `docs/issues/089`; it was `None`.
    assert strategy.memory == {}


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


def test_a_callback_frames_its_memory_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record `239`. The 0.13.0 stop-loss trace (`experiments/exp_238`, `10_run_stoploss`,
    #14667 .. #14971) showed one callback normalizing its memory five times and hashing the
    envelope twice: once to take the ref, once inside that framing, twice to hand the live
    Strategy detached copies, and once more when the root took the same memory and payload.
    The callback frames the candidate once and hands the root what it framed; the two copies
    the live Strategy is given stay -- they are what keeps it from aliasing the root's memory.
    """
    from vqapr.domain import memory as memory_module
    from vqapr.flow.engine import run_state as run_state_module
    from vqapr.flow.run import callback as callback_module

    # Built before the counting starts: the repository frames its seed state once per run.
    state = _state()
    framed: list[str] = []
    normalized: list[str] = []
    for module, name in (
        (callback_module, "prepare_model_state"),
        (run_state_module, "prepare_model_state"),
    ):
        original = getattr(module, name)

        def counting(*args, _module=module.__name__, _original=original, **kwargs):
            framed.append(_module)
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, counting)
    for module in (callback_module, run_state_module, memory_module):
        original = module.normalize_memory

        def counting_normalize(value, _module=module.__name__, _original=original):
            normalized.append(_module)
            return _original(value)

        monkeypatch.setattr(module, "normalize_memory", counting_normalize)

    occurrences = (_occurrence(1), _occurrence(2))
    result = _flow(EveryThreeOccurrences(), state, occurrences).run()

    assert [type(trace.result) for trace in result.occurrences] == [Hold, Hold]
    assert state.load_model_state(result.final_state.current_model_state_ref) == {
        "occurrence_count": 2
    }
    callbacks = len(occurrences)
    assert framed == ["vqapr.flow.run.callback"] * callbacks, (
        f"{len(framed)} framings for {callbacks} callbacks: {framed}"
    )
    # Per callback: the framing's own copy, the two the live Strategy is handed, and the two
    # detached copies the restore before `decide` makes (the Strategy's and the components').
    # Before record `239` two more sat between them: the framing's input normalized on its own,
    # and the root framing the same memory and payload again. The `+ 2` is once per run: the seed
    # state's framing and the opening memory it is framed from, which `opening_memory` normalizes
    # in `domain/memory.py` beside `prepare_model_state` (record `268` measured 12 calls from the
    # same callers on both layouts; only this test's patching boundary moved).
    assert len(normalized) <= 5 * callbacks + 2, f"{len(normalized)} for {callbacks} callbacks"


def test_a_callback_frames_what_it_read_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record `246`. The 0.14.2 factor trace (`experiments/exp_246`, `08_run_factor`) showed
    every callback deriving its source refs twice -- once for the intent's stamp, once for the
    evidence -- from the same window's accesses, and asking the Strategy's `inputs()` again on
    every decision (fifteen askings per ten-decision run). What a callback read is framed once
    after `decide` and handed to both; the declaration is resolved once per run, as
    `ComputeHandler` already did.
    """
    from vqapr.flow.run.callback import CallbackHandler

    asked: list[str] = []

    class CountsItsDeclaration(EveryThreeOccurrences):
        def inputs(self):  # type: ignore[no-untyped-def]
            asked.append("inputs")
            return super().inputs()

    framed: list[str] = []
    original = CallbackHandler._actual_source_refs

    def counting(self: CallbackHandler, window: ModelWindow):  # type: ignore[no-untyped-def]
        framed.append("refs")
        return original(self, window)

    monkeypatch.setattr(CallbackHandler, "_actual_source_refs", counting)
    # Two Holds: this flow has no execution table, so an intent cannot be accepted here; the
    # intent path is counted on a real run in `tests/flow/declaration/test_preflight.py`.
    occurrences = (_occurrence(1), _occurrence(2))
    result = _flow(CountsItsDeclaration(), _state(), occurrences).run()

    assert [type(trace.result) for trace in result.occurrences] == [Hold, Hold]
    assert framed == ["refs"] * len(occurrences), (
        f"{len(framed)} framings of the source refs for {len(occurrences)} callbacks"
    )
    assert asked == ["inputs"], f"inputs() asked {len(asked)} times for one run"
