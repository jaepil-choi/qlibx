"""The strategy run's event loop: one frozen strategy, its callbacks, and the due items they mint.

Record `147` (deletion campaign Step 6) split the loop from the work: the callback handler
(`callback.py`), the execution handler (`execution.py`) and the valuation handler
(`valuation.py`) are where the work is, and `context.py` is what they share. Record
`182` made the loop itself `EventLoop` (`flow/loop.py`): this class supplies the schedule, the
one pending due event, and `handle`, which routes a scheduled event to the callback handler and
a due event to the execution or valuation handler. The names this module re-exports are the ones
callers and tests imported from it before the split.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from vqapr.account.account import Account
from vqapr.account.marking import ValuationService
from vqapr.authoring import AccountHistoryInput, Component, Constraint, StrategyModel
from vqapr.data.scan import ScanSession
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.instruments import InstrumentRoster
from vqapr.exchange.venue import Exchange
from vqapr.flow.declaration.frozen import FrozenRun, FrozenStrategy
from vqapr.flow.engine.artifacts import (
    FinalizationEvidence,
    SimulationStage,
)
from vqapr.flow.engine.loop import EventLoop, MarketEvent, OccurrenceEvent
from vqapr.flow.engine.run_state import (
    RunFinalization,
    RunStateRepository,
)
from vqapr.flow.strategy.accrual import AccrualHandler
from vqapr.flow.strategy.callback import CallbackHandler
from vqapr.flow.strategy.context import (
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    AcceptedIntent,
    DueExecutionResult,
    DueExecutionTrace,
    FailedAfterCommit,
    FlowContext,
    HeldResult,
    MonitoringResult,
    OccurrenceTrace,
    SimulationResult,
    ValuationResult,
    _require_constraint_identity,
    callback_evidence,
)

# Re-exported under the names tests imported from this module before the split (record `147`).
from vqapr.flow.strategy.context import _shadows_package_table as _shadows_package_table
from vqapr.flow.strategy.execution import ExecutionHandler
from vqapr.flow.strategy.valuation import ValuationHandler
from vqapr.flow.strategy.valuation import (
    _marks_from_execution_snapshot as _marks_from_execution_snapshot,
)

__all__ = [
    "DEFAULT_TABLES",
    "DEFAULT_TABLE_PREFIX",
    "AcceptedIntent",
    "DueExecutionResult",
    "DueExecutionTrace",
    "FailedAfterCommit",
    "MonitoringResult",
    "OccurrenceTrace",
    "SimulationResult",
    "StrategyEventLoop",
    "ValuationResult",
    "callback_evidence",
]


class _InstantOccurrence:
    """What a per-occurrence window factory reads when handed a bare instant."""

    __slots__ = ("evaluation_time",)

    def __init__(self, evaluation_time: datetime) -> None:
        self.evaluation_time = evaluation_time


class StrategyEventLoop(
    EventLoop[
        OccurrenceEvent | MarketEvent, OccurrenceTrace | DueExecutionTrace, SimulationResult
    ]
):
    """Walk the strategy clock and the market clock, merged (design §3).

    The Flow owns timestamp stamping, exact execution, account mutation, and marking. The walk
    itself is `EventLoop`'s, shared with a datamodel run (record `148`); what this adds is the
    market clock -- every instant the execution table has inside the run -- and the three
    handlers: a market instant fills the pending intent due there or values the held book, and
    judges the result; an occurrence asks the strategy to decide.
    """

    def __init__(
        self,
        frozen_run: FrozenRun,
        strategy: StrategyModel,
        state: RunStateRepository,
        *,
        layer: FrozenStrategy | None = None,
        strategy_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        constraint_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        account: Account,
        constraint_window_at: Callable[[datetime], ModelWindow] | None = None,
        exchange: Exchange,
        constraints: tuple[Constraint, ...],
        valuation_service: ValuationService | None = None,
        scan_session: ScanSession | None = None,
        on_progress: Callable[[], None] | None = None,
        registry: InstrumentRoster | None = None,
        record_account_positions: bool = True,
    ) -> None:
        # A run runs ONE strategy (2026-09-09,
        # `docs/design/two-clocks-and-the-wiring-table.md` §2.3), so `layer` is a courtesy the
        # caller may pass and never a choice: the run holds the answer.
        if layer is None:
            layer = frozen_run.strategy
        if layer is None or layer is not frozen_run.strategy:
            raise ValueError("layer must be the frozen run's strategy")
        if not callable(strategy_window_for_occurrence):
            raise TypeError("strategy_window_for_occurrence must be callable")
        if not callable(constraint_window_for_occurrence):
            raise TypeError("constraint_window_for_occurrence must be callable")
        if not callable(getattr(exchange, "execute", None)):
            raise TypeError("exchange must provide execute")
        declared = layer.constraints.constraints
        _require_constraint_identity(constraints, declared)
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("simulation start requires a frozen boundary")
        requirements = tuple(getattr(exchange, "execution_requirements", tuple)())
        prices = {requirement.price for requirement in requirements}
        if len(prices) > 1:
            raise ValueError("an Exchange may require at most one reference execution price")
        declared_history = strategy.account_history()
        if declared_history is not None and not isinstance(declared_history, AccountHistoryInput):
            raise TypeError("account_history must return an AccountHistoryInput or None")
        initial = state.current.account
        if initial is None:
            raise ValueError("state must begin with the frozen AccountState root")
        if frozen_run.initial_account_snapshot != initial.snapshot:
            raise ValueError("state AccountState must match FrozenRun initial account snapshot")
        if frozen_run.initial_account_mode != account.mode:
            raise ValueError("Account mode must match FrozenRun initial account mode")
        carried = set(state.current.component_state_refs)
        stateful = {constraint.constraint_id for constraint in constraints}
        if isinstance(exchange, Component):
            stateful.add(exchange.exchange_id)
        if carried != stateful:
            raise ValueError(
                "state must carry the initial memory of exactly the loaded components -- every "
                "constraint, and the venue when it is a Component (RunStateRepository "
                f"initial_component_memory): carrying {sorted(carried)!r}, loaded "
                f"{sorted(stateful)!r}"
            )

        # All handler dependencies exist before the first handler is constructed. The loop owns
        # its schedule and progress hook; the context owns this strategy's runtime and bookkeeping.
        super().__init__(
            schedule=frozen_run.dispatch_order(layer), start_cutoff=cutoff, on_progress=on_progress
        )
        self._context = FlowContext(
            frozen_run=frozen_run,
            layer=layer,
            state=state,
            account=account,
            exchange=exchange,
            strategy=strategy,
            constraints=constraints,
            valuation_service=valuation_service or ValuationService(),
            strategy_window_for_occurrence=strategy_window_for_occurrence,
            constraint_window_for_occurrence=constraint_window_for_occurrence,
            # Direct flow callers may provide only the per-occurrence window factory.
            constraint_window_at=constraint_window_at
            or (
                lambda instant: constraint_window_for_occurrence(
                    _InstantOccurrence(instant)  # type: ignore[arg-type]
                )
            ),
            scan_session=scan_session,
            registry=registry,
            reference_price=next(iter(prices), None),
            record_account_positions=record_account_positions,
            account_history_declaration=declared_history,
        )
        self._accrual = AccrualHandler(self._context)
        self._valuation = ValuationHandler(self._context)
        self._callback = CallbackHandler(self._context)
        self._execution = ExecutionHandler(self._context)
        account.bind(initial)

    def run(self) -> SimulationResult:
        """Synchronously process the static merge and all due items in its horizon."""
        started = time.perf_counter()
        result = super().run()
        # The phases the context accumulated, plus the whole: what the record reports as `timing`
        # (`docs/issues/archive/068`). `total` covers the loop itself; the panel build and the
        # record freeze happen outside it and are the caller's to time.
        timing = {**self._context.timing, "total": time.perf_counter() - started}
        return replace(result, timing=timing)

    def start(self, cutoff: datetime) -> None:
        with self._context.guard(
            SimulationStage.START,
            cutoff,
            owner=self._context.layer.config,
        ):
            self._callback.load_visible_state()

    def events(self) -> tuple[OccurrenceEvent | MarketEvent, ...]:
        """The strategy clock merged with the market clock (design §3).

        The market clock is every instant the execution table has inside `[start, end]`, read
        once through the run's horizon -- the same read the fill rule bisects, so the instants a
        decision can fill at and the instants the book is valued at are one set. A run declared
        without execution authority has no market clock and is the plain sequence of decisions.
        """
        occurrences: tuple[OccurrenceEvent | MarketEvent, ...] = tuple(
            OccurrenceEvent(item) for item in self.schedule
        )
        execution_table = self._context.frozen_run.execution
        if execution_table is None:
            return occurrences
        horizon = self._callback.execution_horizon(execution_table)
        return (*occurrences, *(MarketEvent(instant) for instant in horizon.instants))

    def handle(
        self, event: OccurrenceEvent | MarketEvent
    ) -> OccurrenceTrace | DueExecutionTrace:
        if isinstance(event, MarketEvent):
            return self._handle_market(event)
        # A scheduled event is a callback, always (record `182`: an occurrence carries no role to
        # branch on). `callback` is the whole scheduled side: the window built for the model and
        # the model's own `decide` (`docs/issues/archive/068`: a user learns their strategy is 5%
        # of the wall clock from the record, not from cProfile).
        with self._context.timed("callback"):
            return self._callback.dispatch(event.occurrence)

    def _handle_market(self, event: MarketEvent) -> DueExecutionTrace:
        """One instant of the market clock, in the order design §3.1 fixes -- written once, here.

            1. ACCRUE      what the holding period up to now earned         (a place, for now)
            2. EXECUTE     the pending intent whose target is this instant  (when there is one)
            3. VALUATION   the committed book, from the fill's snapshot or a fresh one
            4. COMPLIANCE  the declared constraints on the committed, marked book
            (5. DECIDE     a decision at this same instant is a separate event, sorted after)

        A pending intent whose target has already passed is a broken invariant, not a late fill:
        targets are selected from this same clock, so the instant was walked.
        """
        instant = event.instant
        with (
            self._context.timed("due"),
            self._context.guard(
                SimulationStage.DUE_SNAPSHOT, instant, owner=self._context.frozen_run.execution
            ),
        ):
            pending = self._context.state.current.pending_accepted_intent
            if pending is not None and not isinstance(pending, AcceptedIntent):
                raise TypeError("run state pending must be an AcceptedIntent")
            if pending is not None and pending.target.target_at < instant:
                raise RuntimeError("a pending intent's target instant was never walked")
            due = pending if pending is not None and pending.target.target_at == instant else None

            self._accrual.accrue(instant)
            filled = None if due is None else self._execution.fill(due)
            if filled is not None and self._context.state.current.pending_accepted_intent:
                raise RuntimeError("due execution failed to consume its pending identity")
            marked = (
                self._valuation.mark_held(instant)
                if filled is None
                else self._valuation.mark_fill(filled)
            )
            monitoring = self._valuation.monitor_at(
                instant, occurrence=None if filled is None else filled.pending.occurrence
            )
            result: DueExecutionResult | HeldResult = (
                HeldResult(marked.evidence, monitoring)  # type: ignore[arg-type]
                if filled is None
                else self._execution.close(filled, marked, monitoring)
            )
            return DueExecutionTrace(event, result, self._context.state.current)

    def finish(self, traces: tuple[OccurrenceTrace | DueExecutionTrace, ...]) -> SimulationResult:
        if self._context.state.current.pending_accepted_intent is not None:
            raise RuntimeError("simulation finalized with a pending accepted intent")
        if self._context.frozen_run.end is None:
            raise RuntimeError("simulation finalization requires a frozen end")
        account = self._context.state.current.account
        finalization = FinalizationEvidence(
            run_identity=self._context.frozen_run.identity,
            strategy_agenda=self._context.layer.agenda,
            root_version=self._context.state.current.version,
            cutoff=self._context.frozen_run.end,
            account=None if account is None else account.snapshot,
        )
        with self._context.guard(
            SimulationStage.FINALIZE,
            self._context.frozen_run.end,
            owner=finalization,
        ):
            root = self._context.state.finalize(RunFinalization(finalization))
        return SimulationResult(tuple(traces), root)
