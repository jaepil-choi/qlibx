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
from vqapr.authoring import AccountHistoryInput
from vqapr.constraints.constraint import Constraint
from vqapr.data.windows import ModelWindow
from vqapr.evidence.artifacts import (
    FinalizationEvidence,
    SimulationFailureFamily,
    SimulationStage,
)
from vqapr.exchange.conventions import ExecutionHorizon
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
from vqapr.flow.loop import OccurrenceFlow
from vqapr.flow.run import FrozenRun, FrozenStrategy
from vqapr.flow.run_state import (
    RunFinalization,
    RunStateRepository,
)
from vqapr.flow.valuation import ValuationPhase
from vqapr.flow.valuation import (
    _marks_from_execution_snapshot as _marks_from_execution_snapshot,
)
from vqapr.models.strategy_model import StrategyModel
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.runtime.events import DueExecutionEnvelope
from vqapr.valuation.marking import ValuationService

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
        self._context = FlowContext()
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
        self._context.frozen_run = frozen_run
        self._context.layer = layer
        self._context.static_occurrences = frozen_run.dispatch_order(layer)
        self._static_occurrences = self._context.static_occurrences
        cutoff = frozen_run.start or frozen_run.end
        if cutoff is None:
            raise RuntimeError("simulation start requires a frozen boundary")
        self._start_cutoff = cutoff
        self._context.strategy = strategy
        self._context.state = state
        self._context.strategy_window_for_occurrence = strategy_window_for_occurrence
        self._context.constraint_window_for_occurrence = constraint_window_for_occurrence
        # Monitoring reads as of the fill instant (record `148`). A caller that gave only the
        # per-occurrence factory -- the tests' flows -- gets a window at the decision instead.
        self._context.constraint_window_at = constraint_window_at or (
            lambda instant: constraint_window_for_occurrence(
                _InstantOccurrence(instant)  # type: ignore[arg-type]
            )
        )
        self._context.account = account
        self._context.exchange = exchange
        # The venue names the extra execution price its own regimes need, once per run. A venue
        # that declares none is read exactly as before.
        requirements = tuple(getattr(exchange, "execution_requirements", tuple)())
        prices = {requirement.price for requirement in requirements}
        if len(prices) > 1:
            raise ValueError("an Exchange may require at most one reference execution price")
        self._context.reference_price = next(iter(prices), None)
        self._context.constraints = constraints
        self._context.valuation_service = valuation_service or ValuationService()
        # The run already opens one duckdb handle for observations; the execution table was
        # opening and closing its own on every fill, which is where the time went.
        self._context.scan_session = scan_session
        self._context.on_progress = on_progress
        self._on_progress = on_progress
        if not isinstance(record_account_positions, bool):
            raise TypeError("record_account_positions must be a bool")
        # Whether `vqapr.account` carries one row per held instrument at every valuation, or the
        # `_ACCOUNT` row alone. Declared in the run spec's `store:` block; the testbed's broad
        # signed book wrote 2.6M position rows of which the rows actually read were 0.07%.
        self._context.record_account_positions = record_account_positions
        # The project's instrument roster, bound into the venue's view at the one seam a category
        # enters through. Optional so a flow assembled without one still constructs; what it
        # cannot then do is answer what an instrument is, which it refuses rather than guesses.
        self._context.registry = registry
        # Bound onto the venue now, not per occurrence: `execute` reads the venue's own rules and
        # never receives one passed down, so binding only at the call site left every `Fill.kind`
        # null while a registered roster sat unused in the workspace.
        self._valuation = ValuationPhase(self._context, None)  # type: ignore[arg-type]
        self._callback = CallbackPhase(self._context, self._valuation)
        self._valuation._callback = self._callback
        self._execution = ExecutionPhase(self._context, self._valuation)
        self._execution.bind_registry_to_venue()
        declared = strategy.account_history()
        if declared is not None and not isinstance(declared, AccountHistoryInput):
            raise TypeError("account_history must return an AccountHistoryInput or None")
        # One declaration, one projection per callback: the run has one Strategy, and what it
        # declares is both what each callback reads and what the Account retains.
        self._context.account_history_declaration = declared
        self._context.horizon: ExecutionHorizon | None = None
        self._context.recorded_measurements: set[object] = set()
        """Measurement instants already written to `vqapr.account`, by whichever path wrote them.

        Keyed on the instant a mark was TAKEN, not on the occurrence that wrote it, because that
        is the axis a reader dates the series by. Two rows for one instant pair a real value with
        a duplicate; 056 measured that as HML 0.9726 -> 0.6877.
        """
        initial = state.current.account
        if not isinstance(initial, AccountState):
            raise ValueError("state must begin with the frozen AccountState root")
        if frozen_run.initial_account_snapshot != initial.snapshot:
            raise ValueError("state AccountState must match FrozenRun initial account snapshot")
        if frozen_run.initial_account_mode != account.mode:
            raise ValueError("Account mode must match FrozenRun initial account mode")
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
        self._context.guard(
            SimulationStage.START,
            cutoff,
            self._callback.load_visible_strategy_state,
            family=SimulationFailureFamily.DATA,
            owner=self._context.layer.config,
        )

    def _dispatch_static(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        if occurrence.role is OperationRole.STRATEGY_CALLBACK:
            # `callback` is the whole static side: the window built for the model and the
            # model's own `decide` (`docs/issues/068`: a user learns their strategy is 5% of
            # the wall clock from the record, not from cProfile).
            return self._context.timed(  # type: ignore[return-value]
                "callback", lambda: self._callback.dispatch(occurrence)
            )
        # Record `148`: valuation happens at the execution instant and monitoring right after
        # each commit, inside the due path. A static occurrence of any other role is a
        # malformed agenda, not a phase to dispatch to.
        raise ValueError(f"unsupported operation role: {occurrence.role!r}")

    def _dispatch_due(self, due: DueExecutionEnvelope) -> DueExecutionTrace:
        return self._context.timed(  # type: ignore[return-value]
            "due",
            lambda: self._context.guard(
                SimulationStage.DUE_SNAPSHOT,
                due.due_time,
                lambda: self._dispatch_pending(due),
                family=SimulationFailureFamily.DATA,
                owner=self._context.frozen_run.execution_input,
            ),
        )

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
        root = self._context.guard(
            SimulationStage.FINALIZE,
            self._context.frozen_run.end,
            lambda: self._context.state.finalize(RunFinalization(finalization)),
            family=SimulationFailureFamily.FINALIZATION,
            owner=finalization,
        )
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

