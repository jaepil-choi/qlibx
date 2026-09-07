"""Frequency-agnostic deterministic dispatcher for one frozen simulation run.

Record `147` (deletion campaign Step 6): this module is the loop. One occurrence at a time it
decides which phase an occurrence goes to and hands it over; the callback phase
(`flow/callback.py`), the execution phase (`flow/execution.py`) and the valuation phase
(`flow/valuation.py`) are where the work is, and `flow/context.py` is what they share. The names
this module re-exports are the ones callers and tests imported from it before the split.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from vqapr.account.account import Account
from vqapr.account.snapshot import AccountState
from vqapr.authoring import AccountHistoryInput, Constraint, StrategyModel
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence, OperationRole
from vqapr.evidence.artifacts import (
    FinalizationEvidence,
    SimulationFailureFamily,
    SimulationStage,
)
from vqapr.exchange.venue import Exchange
from vqapr.flow.callback import CallbackPhase
from vqapr.flow.context import (
    DEFAULT_TABLE_PREFIX,
    DEFAULT_TABLES,
    AcceptedIntent,
    DueExecutionResult,
    DueExecutionTrace,
    FailedAfterCommit,
    FlowContext,
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
from vqapr.flow.execution import ExecutionPhase
from vqapr.flow.frozen import FrozenRun, FrozenStrategy
from vqapr.flow.loop import DueExecutionEnvelope, OccurrenceFlow
from vqapr.flow.marking import ValuationService
from vqapr.flow.run_state import (
    RunFinalization,
    RunStateRepository,
)
from vqapr.flow.valuation import ValuationPhase
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
    "SimulationFlow",
    "SimulationResult",
    "ValuationResult",
    "callback_evidence",
]


class _InstantOccurrence:
    """What a per-occurrence window factory reads when handed a bare instant."""

    __slots__ = ("evaluation_time",)

    def __init__(self, evaluation_time: datetime) -> None:
        self.evaluation_time = evaluation_time


class SimulationFlow(OccurrenceFlow):
    """Dispatch frozen occurrences and one latest accepted pending intent.

    The Flow owns timestamp stamping, exact execution, account mutation, and marking. The walk
    itself is `OccurrenceFlow`'s, shared with a datamodel run (record `148`); what this adds is
    the three phases an occurrence and its due item dispatch to.
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
        scan_session: object | None = None,
        on_progress: Callable[[], None] | None = None,
        registry: object | None = None,
        record_account_positions: bool = True,
    ) -> None:
        if not isinstance(frozen_run, FrozenRun):
            raise TypeError("frozen_run must be a FrozenRun")
        # One flow runs ONE strategy of the run (record `139`): the run layer is shared, the
        # strategy layer is this flow's own. A run with one strategy needs no `layer`.
        if layer is None:
            if len(frozen_run.strategies) != 1:
                raise ValueError(
                    "a run with several strategies must say which one this flow runs (layer=)"
                )
            layer = frozen_run.strategies[0]
        if not isinstance(layer, FrozenStrategy) or layer not in frozen_run.strategies:
            raise TypeError("layer must be one of the frozen run's strategies")
        if not isinstance(strategy, StrategyModel):
            raise TypeError("strategy must be a StrategyModel")
        if not isinstance(state, RunStateRepository):
            raise TypeError("state must be a RunStateRepository")
        if not callable(strategy_window_for_occurrence):
            raise TypeError("strategy_window_for_occurrence must be callable")
        if not callable(constraint_window_for_occurrence):
            raise TypeError("constraint_window_for_occurrence must be callable")
        if not isinstance(account, Account):
            raise TypeError("account must be an Account")
        if not callable(getattr(exchange, "execute", None)):
            raise TypeError("exchange must provide execute")
        if not isinstance(constraints, tuple) or not all(
            isinstance(constraint, Constraint) for constraint in constraints
        ):
            raise TypeError("constraints must be a tuple of Constraint implementations")
        declared = layer.constraints.constraints
        _require_constraint_identity(constraints, declared)
        if valuation_service is not None and not isinstance(valuation_service, ValuationService):
            raise TypeError("valuation_service must be a ValuationService or None")
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("simulation start requires a frozen boundary")
        if not isinstance(record_account_positions, bool):
            raise TypeError("record_account_positions must be a bool")
        requirements = tuple(getattr(exchange, "execution_requirements", tuple)())
        prices = {requirement.price for requirement in requirements}
        if len(prices) > 1:
            raise ValueError("an Exchange may require at most one reference execution price")
        declared_history = strategy.account_history()
        if declared_history is not None and not isinstance(declared_history, AccountHistoryInput):
            raise TypeError("account_history must return an AccountHistoryInput or None")
        initial = state.current.account
        if not isinstance(initial, AccountState):
            raise ValueError("state must begin with the frozen AccountState root")
        if frozen_run.initial_account_snapshot != initial.snapshot:
            raise ValueError("state AccountState must match FrozenRun initial account snapshot")
        if frozen_run.initial_account_mode != account.mode:
            raise ValueError("Account mode must match FrozenRun initial account mode")

        # All phase dependencies exist before the first phase is constructed. The loop owns
        # its agenda and progress hook; the context owns this strategy's runtime and bookkeeping.
        self._static_occurrences = frozen_run.dispatch_order(layer)
        self._start_cutoff = cutoff
        self._on_progress = on_progress
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
        self._valuation = ValuationPhase(self._context)
        self._callback = CallbackPhase(self._context)
        self._execution = ExecutionPhase(self._context, self._valuation)
        self._execution.bind_registry_to_venue()
        account.bind(initial)

    def run(self) -> SimulationResult:
        """Synchronously process the static merge and all due items in its horizon."""
        started = time.perf_counter()
        result = super().run()
        assert isinstance(result, SimulationResult)
        # The phases the context accumulated, plus the whole: what the record reports as
        # `timing` (`docs/issues/068`). `total` covers the loop itself; the panel build and the
        # record freeze happen outside it and are the caller's to time.
        timing = {**self._context.timing, "total": time.perf_counter() - started}
        return replace(result, timing=timing)

    def _start(self, cutoff: datetime) -> None:
        with self._context.guard(
            SimulationStage.START,
            cutoff,
            family=SimulationFailureFamily.DATA,
            owner=self._context.layer.config,
        ):
            self._callback.load_visible_strategy_state()

    def _dispatch_static(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        if occurrence.role is OperationRole.STRATEGY_CALLBACK:
            # `callback` is the whole static side: the window built for the model and the
            # model's own `decide` (`docs/issues/068`: a user learns their strategy is 5% of
            # the wall clock from the record, not from cProfile).
            with self._context.timed("callback"):
                return self._callback.dispatch(occurrence)
        # Record `148`: valuation happens at the execution instant and monitoring right after
        # each commit, inside the due path. A static occurrence of any other role is a
        # malformed agenda, not a phase to dispatch to.
        raise ValueError(f"unsupported operation role: {occurrence.role!r}")

    def _dispatch_due(self, due: DueExecutionEnvelope) -> DueExecutionTrace:
        with (
            self._context.timed("due"),
            self._context.guard(
                SimulationStage.DUE_SNAPSHOT,
                due.due_time,
                family=SimulationFailureFamily.DATA,
                owner=self._context.frozen_run.execution_input,
            ),
        ):
            return self._dispatch_pending(due)

    def _finish(self, traces: tuple[object, ...]) -> SimulationResult:
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
            family=SimulationFailureFamily.FINALIZATION,
            owner=finalization,
        ):
            root = self._context.state.finalize(RunFinalization(finalization))
        return SimulationResult(tuple(traces), root)  # type: ignore[arg-type]

    def _pending_due(self) -> DueExecutionEnvelope | None:
        pending = self._context.state.current.pending_accepted_intent
        if pending is None:
            return None
        if not isinstance(pending, (AcceptedIntent, PendingValuation)):
            raise TypeError("run state pending must be an AcceptedIntent or PendingValuation")
        return DueExecutionEnvelope(pending.target.target_at, pending.pending_id)

    def _dispatch_pending(self, due: DueExecutionEnvelope) -> DueExecutionTrace:
        pending = self._context.state.current.pending_accepted_intent
        if (
            not isinstance(pending, (AcceptedIntent, PendingValuation))
            or pending.pending_id != due.pending_id
        ):
            raise RuntimeError("pending intent changed while dispatching due execution")
        if isinstance(pending, PendingValuation):
            result: object = self._valuation.value_due(pending)
        else:
            result = self._execution.execute_due(pending)
        if self._context.state.current.pending_accepted_intent is not None:
            raise RuntimeError("due execution failed to consume its pending identity")
        return DueExecutionTrace(due, result, self._context.state.current)
