"""The strategy run's event loop: one frozen strategy, its callbacks, and the due items they mint.

Record `147` (deletion campaign Step 6) split the loop from the work: the callback handler
(`flow/callback.py`), the execution handler (`flow/execution.py`) and the valuation handler
(`flow/valuation.py`) are where the work is, and `flow/context.py` is what they share. Record
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
from vqapr.authoring import AccountHistoryInput, Component, Constraint, StrategyModel
from vqapr.data.scan import ScanSession
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.instruments import InstrumentRoster
from vqapr.evidence.artifacts import (
    FinalizationEvidence,
    SimulationStage,
)
from vqapr.exchange.venue import Exchange
from vqapr.flow.callback import CallbackHandler
from vqapr.flow.context import (
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
    PendingValuation,
    SimulationResult,
    ValuationResult,
    _require_constraint_identity,
    callback_evidence,
)

# Re-exported under the names tests imported from this module before the split (record `147`).
from vqapr.flow.context import _shadows_package_table as _shadows_package_table
from vqapr.flow.execution import ExecutionHandler
from vqapr.flow.frozen import FrozenRun, FrozenStrategy
from vqapr.flow.loop import DueEvent, EventLoop, OccurrenceEvent
from vqapr.flow.marking import ValuationService
from vqapr.flow.run_state import (
    RunFinalization,
    RunStateRepository,
)
from vqapr.flow.valuation import ValuationHandler
from vqapr.flow.valuation import (
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
    "PendingValuation",
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
    EventLoop[OccurrenceEvent | DueEvent, OccurrenceTrace | DueExecutionTrace, SimulationResult]
):
    """Dispatch frozen occurrences and one latest accepted pending intent.

    The Flow owns timestamp stamping, exact execution, account mutation, and marking. The walk
    itself is `EventLoop`'s, shared with a datamodel run (record `148`); what this adds is
    the three handlers a scheduled event and a due event are routed to.
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
        # One flow runs ONE strategy of the run (record `139`): the run layer is shared, the
        # strategy layer is this flow's own. A run with one strategy needs no `layer`.
        if layer is None:
            if len(frozen_run.strategies) != 1:
                raise ValueError(
                    "a run with several strategies must say which one this flow runs (layer=)"
                )
            layer = frozen_run.strategies[0]
        if layer not in frozen_run.strategies:
            raise ValueError("layer must be one of the frozen run's strategies")
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
        self._valuation = ValuationHandler(self._context)
        self._callback = CallbackHandler(self._context)
        self._execution = ExecutionHandler(self._context, self._valuation)
        account.bind(initial)

    def run(self) -> SimulationResult:
        """Synchronously process the static merge and all due items in its horizon."""
        started = time.perf_counter()
        result = super().run()
        # The phases the context accumulated, plus the whole: what the record reports as
        # `timing` (`docs/issues/068`). `total` covers the loop itself; the panel build and the
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

    def handle(self, event: OccurrenceEvent | DueEvent) -> OccurrenceTrace | DueExecutionTrace:
        if isinstance(event, DueEvent):
            return self._handle_due(event)
        # A scheduled event is a callback, always (record `148`: valuation happens at the
        # execution instant and monitoring right after each commit, inside the due path; record
        # `182`: an occurrence carries no role to branch on). `callback` is the whole scheduled
        # side: the window built for the model and the model's own `decide` (`docs/issues/068`:
        # a user learns their strategy is 5% of the wall clock from the record, not from
        # cProfile).
        with self._context.timed("callback"):
            return self._callback.dispatch(event.occurrence)

    def _handle_due(self, due: DueEvent) -> DueExecutionTrace:
        with (
            self._context.timed("due"),
            self._context.guard(
                SimulationStage.DUE_SNAPSHOT,
                due.due_time,
                owner=self._context.frozen_run.execution,
            ),
        ):
            return self._dispatch_pending(due)

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

    def pending(self) -> DueEvent | None:
        pending = self._context.state.current.pending_accepted_intent
        if pending is None:
            return None
        if not isinstance(pending, (AcceptedIntent, PendingValuation)):
            raise TypeError("run state pending must be an AcceptedIntent or PendingValuation")
        return DueEvent(pending.target.target_at, pending.pending_id)

    def _dispatch_pending(self, due: DueEvent) -> DueExecutionTrace:
        pending = self._context.state.current.pending_accepted_intent
        if (
            not isinstance(pending, (AcceptedIntent, PendingValuation))
            or pending.pending_id != due.pending_id
        ):
            raise RuntimeError("pending intent changed while dispatching due execution")
        if isinstance(pending, PendingValuation):
            result: DueExecutionResult | HeldResult = self._valuation.value_due(pending)
        else:
            result = self._execution.execute_due(pending)
        if self._context.state.current.pending_accepted_intent is not None:
            raise RuntimeError("due execution failed to consume its pending identity")
        return DueExecutionTrace(due, result, self._context.state.current)
