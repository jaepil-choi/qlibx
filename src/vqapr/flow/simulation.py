"""Frequency-agnostic deterministic dispatcher for one frozen simulation run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from vqapr.account.account import Account
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import Constraint
from vqapr.constraints.evaluation import evaluate_constraints
from vqapr.constraints.findings import ConstraintReport
from vqapr.data.windows import ModelWindow
from vqapr.exchange.conventions import ExactExecutionTarget
from vqapr.exchange.execution_table import exact_execution_snapshot
from vqapr.exchange.venue import Exchange
from vqapr.flow.run import FrozenRun
from vqapr.flow.run_state import (
    AcceptedRunState,
    RunStateRepository,
    capture_live_memory,
    restore_live_memory,
)
from vqapr.models.contexts import StrategyModelContext
from vqapr.models.memory import normalize_memory
from vqapr.models.strategy_model import NoDecision, StrategyModel
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.intents import EconomicPortfolioIntent, validate_economic_intent
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.runtime.events import DueExecutionEnvelope, OperationEnvelope
from vqapr.valuation.configuration import ValuationConfig
from vqapr.valuation.marking import SelectedMark, ValuationService
from vqapr.valuation.marks import MarkBatch


@dataclass(frozen=True, slots=True)
class AcceptedIntent:
    """A timestamp-free Strategy payload bound to one Flow-selected target."""

    intent: EconomicPortfolioIntent
    occurrence: OperationOccurrence
    decision_time: datetime
    target: ExactExecutionTarget

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")
        if self.decision_time != self.occurrence.evaluation_time:
            raise ValueError("decision_time must be the current occurrence evaluation_time")
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if not isinstance(self.target, ExactExecutionTarget):
            raise TypeError("target must be an ExactExecutionTarget")
        target_at = self.target.target_at
        if target_at.astimezone(UTC) <= self.decision_time.astimezone(UTC):
            raise ValueError("execution target must be strictly later than decision_time")

    @property
    def pending_id(self) -> str:
        return str(self.intent.intent_id)


@dataclass(frozen=True, slots=True)
class OccurrenceTrace:
    occurrence: OperationOccurrence
    result: object
    state: AcceptedRunState


@dataclass(frozen=True, slots=True)
class SimulationResult:
    occurrences: tuple[OccurrenceTrace, ...]
    final_state: AcceptedRunState


@dataclass(frozen=True, slots=True)
class DueExecutionResult:
    """Evidence returned only after the complete post-decision account chain."""

    consumed_pending_id: str
    account_version: int
    post_account_result: object

    def __post_init__(self) -> None:
        if not isinstance(self.consumed_pending_id, str) or not self.consumed_pending_id:
            raise ValueError("consumed_pending_id must be a non-empty string")
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")


@dataclass(frozen=True, slots=True)
class ValuationResult:
    """A complete selected mark set for one committed AccountSnapshot."""

    account: AccountSnapshot
    marks: MarkBatch

    def __post_init__(self) -> None:
        if not isinstance(self.account, AccountSnapshot):
            raise TypeError("account must be an AccountSnapshot")
        if not isinstance(self.marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")


@dataclass(frozen=True, slots=True)
class MonitoringResult:
    """Constraint evidence over exactly the AccountSnapshot just marked."""

    valuation: ValuationResult
    report: ConstraintReport

    def __post_init__(self) -> None:
        if not isinstance(self.valuation, ValuationResult):
            raise TypeError("valuation must be a ValuationResult")
        if not isinstance(self.report, ConstraintReport):
            raise TypeError("report must be a ConstraintReport")
        if self.report.account_version != self.valuation.account.version:
            raise ValueError("report must evaluate the marked account version")


class SimulationFlow:
    """Dispatch frozen occurrences and one latest accepted pending intent.

    The Flow owns timestamp stamping, exact execution, account mutation, and marking.
    """

    def __init__(
        self,
        frozen_run: FrozenRun,
        strategy: StrategyModel,
        state: RunStateRepository,
        *,
        window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        account: Account,
        exchange: Exchange,
        constraints: tuple[Constraint, ...],
        marks_for_occurrence: Callable[
            [ValuationConfig, OperationOccurrence, AccountSnapshot],
            Mapping[str, Decimal] | tuple[SelectedMark, ...],
        ],
        valuation_service: ValuationService | None = None,
    ) -> None:
        if not isinstance(frozen_run, FrozenRun):
            raise TypeError("frozen_run must be a FrozenRun")
        if not isinstance(strategy, StrategyModel):
            raise TypeError("strategy must be a StrategyModel")
        if not isinstance(state, RunStateRepository):
            raise TypeError("state must be a RunStateRepository")
        if not callable(window_for_occurrence):
            raise TypeError("window_for_occurrence must be callable")
        if not isinstance(account, Account):
            raise TypeError("account must be an Account")
        if not callable(getattr(exchange, "execute", None)):
            raise TypeError("exchange must provide execute")
        if not isinstance(constraints, tuple) or not all(
            isinstance(constraint, Constraint) for constraint in constraints
        ):
            raise TypeError("constraints must be a tuple of Constraint implementations")
        declared = frozen_run.constraints.constraints
        if len(constraints) != len(declared):
            raise ValueError("loaded constraints must exactly match FrozenRun ConstraintSet")
        if tuple(constraint.constraint_id for constraint in constraints) != tuple(
            str(component.component_id) for component in declared
        ):
            raise ValueError("loaded constraints must preserve FrozenRun ConstraintSet identity")
        if not callable(marks_for_occurrence):
            raise TypeError("marks_for_occurrence must be callable")
        if valuation_service is not None and not isinstance(valuation_service, ValuationService):
            raise TypeError("valuation_service must be a ValuationService or None")
        self._frozen_run = frozen_run
        self._strategy = strategy
        self._state = state
        self._window_for_occurrence = window_for_occurrence
        self._account = account
        self._exchange = exchange
        self._constraints = constraints
        self._marks_for_occurrence = marks_for_occurrence
        self._valuation_service = valuation_service or ValuationService()
        self._latest_valuation: ValuationResult | None = None

    def run(self) -> SimulationResult:
        """Synchronously process the static merge and all due items in its horizon."""
        current_ref = self._state.current.current_model_state_ref
        self._strategy.memory = (
            self._state.load_model_state(current_ref) if current_ref is not None else None
        )
        traces: list[OccurrenceTrace] = []
        static = iter(OperationEnvelope(item) for item in self._frozen_run.static_occurrences)
        next_static = next(static, None)

        while next_static is not None or self._pending_due() is not None:
            due = self._pending_due()
            if due is not None and (
                next_static is None or due.sort_key() <= next_static.sort_key()
            ):
                self._dispatch_due(due)
                continue
            assert next_static is not None
            occurrence = next_static.occurrence
            next_static = next(static, None)
            if occurrence.role is OperationRole.STRATEGY_CALLBACK:
                traces.append(self._dispatch_callback(occurrence))
            elif occurrence.role is OperationRole.VALUATION:
                traces.append(self._dispatch_valuation(occurrence))
            elif occurrence.role is OperationRole.MONITORING:
                traces.append(self._dispatch_monitoring(occurrence))
            else:  # OperationRole is closed, but keep malformed values fail-closed.
                raise ValueError(f"unsupported operation role: {occurrence.role!r}")

        if self._state.current.pending_accepted_intent is not None:
            raise RuntimeError("simulation finalized with a pending accepted intent")
        return SimulationResult(tuple(traces), self._state.current)

    def _pending_due(self) -> DueExecutionEnvelope | None:
        pending = self._state.current.pending_accepted_intent
        if pending is None:
            return None
        if not isinstance(pending, AcceptedIntent):
            raise TypeError("run state pending intent must be an AcceptedIntent")
        return DueExecutionEnvelope(pending.target.target_at, pending.pending_id)

    def _dispatch_due(self, due: DueExecutionEnvelope) -> None:
        pending = self._state.current.pending_accepted_intent
        if not isinstance(pending, AcceptedIntent) or pending.pending_id != due.pending_id:
            raise RuntimeError("pending intent changed while dispatching due execution")
        self._execute_due(pending)
        if self._state.current.pending_accepted_intent is not None:
            raise RuntimeError("due execution failed to consume its pending identity")

    def _execute_due(self, pending: AcceptedIntent) -> DueExecutionResult:
        execution_input = self._frozen_run.execution_input
        if execution_input is None:
            raise RuntimeError("due execution requires frozen execution input")
        before = self._account.snapshot()
        targets = pending.intent.targets
        target_instruments = tuple(target.instrument_id for target in targets)
        held_instruments = tuple(before.positions)
        snapshot = exact_execution_snapshot(
            execution_input.table,
            target_at=pending.target.target_at,
            target_instruments=target_instruments,
            held_instruments=held_instruments,
            trade_price=pending.target.trade_price,
        )
        if snapshot.missing_held_instruments:
            missing_held = snapshot.missing_held_instruments
            raise ValueError(
                f"missing selected execution value for held instruments: {missing_held}"
            )
        prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
        required = set(target_instruments).union(held_instruments)
        missing_prices = sorted(required.difference(prices))
        if missing_prices:
            raise ValueError(f"missing selected execution value: {missing_prices}")
        selected_prices = {
            instrument: price for instrument, price in prices.items() if price is not None
        }
        nav = before.cash + sum(
            (
                before.positions[instrument] * selected_prices[instrument]
                for instrument in held_instruments
            ),
            Decimal("0"),
        )
        weights = {
            target.instrument_id: target.weight for target in targets if target.weight is not None
        }
        quantities = {
            target.instrument_id: target.quantity
            for target in targets
            if target.quantity is not None
        }
        orders = plan_orders(
            account=before,
            execution_time_nav=nav,
            prices=selected_prices,
            weight_targets=weights,
            quantity_targets=quantities,
        )
        fills = self._exchange.execute(orders, before, snapshot)
        prepared = self._account.prepare_commit(fills, expected_version=before.version)
        after = self._account.commit(prepared)
        try:
            mark = self._valuation_service.mark(
                after,
                {instrument: selected_prices[instrument] for instrument in after.positions},
            )
        except Exception as error:
            self._state.record_post_account_failure(
                pending_id=pending.pending_id,
                account_declaration=after,
                account_version=after.version,
                fill=fills,
                error=error,
            )
            raise
        root = self._state.complete_due(
            pending_id=pending.pending_id,
            account_declaration=after,
            account_version=after.version,
            fill=fills,
            mark=mark,
            feedback=(mark,),
            evidence={"target": pending.target, "orders": orders},
        )
        return DueExecutionResult(pending.pending_id, root.account_version, mark)

    def _dispatch_valuation(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        account = self._account.snapshot()
        selected_marks = self._marks_for_occurrence(self._frozen_run.valuation, occurrence, account)
        marks = self._valuation_service.mark(account, selected_marks)
        valuation = ValuationResult(account, marks)
        self._latest_valuation = valuation
        return OccurrenceTrace(occurrence, valuation, self._state.current)

    def _dispatch_monitoring(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        valuation = self._latest_valuation
        if valuation is None:
            raise RuntimeError("monitoring occurrence requires a preceding valuation")
        current = self._account.snapshot()
        if current != valuation.account:
            raise RuntimeError(
                "monitoring requires marks for the current committed account snapshot"
            )
        report = evaluate_constraints(self._constraints, valuation.account, valuation.marks)
        return OccurrenceTrace(occurrence, MonitoringResult(valuation, report), self._state.current)

    def _dispatch_callback(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        before = capture_live_memory(self._strategy.memory)
        try:
            window = self._window_for_occurrence(occurrence)
            account = self._account.snapshot()
            if not isinstance(window, ModelWindow):
                raise TypeError("window_for_occurrence must return a ModelWindow")
            result = self._strategy.on_occurrence(
                StrategyModelContext(occurrence=occurrence, window=window, account=account)
            )
            candidate = normalize_memory(self._strategy.memory)
            if isinstance(result, NoDecision):
                root = self._state.accept_no_decision(candidate, detail=result)
            else:
                intent = validate_economic_intent(result)
                if intent.account_version_seen != account.version:
                    raise ValueError(
                        "intent account_version_seen does not match current AccountSnapshot"
                    )
                accepted = self._accept_intent(intent, occurrence)
                root = self._state.accept_intent(candidate, accepted, detail=accepted)
        except Exception:
            restore_live_memory(self._strategy, before)
            raise
        if root.current_model_state_ref is None:
            raise RuntimeError("successful callback did not commit model state")
        self._strategy.memory = root.load_model_state(root.current_model_state_ref)
        return OccurrenceTrace(occurrence, result, root)

    def _accept_intent(
        self, intent: EconomicPortfolioIntent, occurrence: OperationOccurrence
    ) -> AcceptedIntent:
        execution_input = self._frozen_run.execution_input
        if execution_input is None or self._frozen_run.end is None:
            raise ValueError("an accepted intent requires frozen execution input and run end")
        target = execution_input.fill.select_target(
            execution_input,
            decision_time=occurrence.evaluation_time,
            end_time=self._frozen_run.end,
        )
        if target is None:
            raise ValueError("no exact execution target exists within the run horizon")
        accepted = AcceptedIntent(
            intent=intent,
            occurrence=occurrence,
            decision_time=occurrence.evaluation_time,
            target=target,
        )
        if target.execution_input_id != execution_input.execution_input_id:
            raise ValueError(
                "selected target execution input provenance does not match frozen input"
            )
        return accepted
