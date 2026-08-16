"""Frequency-agnostic deterministic dispatcher for one frozen simulation run."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from vqapr.account.account import Account
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.constraints.constraint import Constraint
from vqapr.constraints.evaluation import (
    evaluate_constraints,
    merged_constraint_bounds,
    project_constraints,
    validate_intended_constraints,
)
from vqapr.constraints.findings import ConstraintReport
from vqapr.data.windows import ModelWindow
from vqapr.evidence.artifacts import (
    CallbackEvidence,
    DueExecutionEvidence,
    FinalizationEvidence,
    SimulationFailure,
    ValuationEvidence,
)
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.conventions import ExactExecutionTarget
from vqapr.exchange.execution_table import exact_execution_snapshot
from vqapr.exchange.venue import Exchange
from vqapr.flow.run import FrozenRun
from vqapr.flow.run_state import (
    AcceptedRunState,
    LifecycleKind,
    LifecycleTrace,
    RunFinalization,
    RunStateRepository,
)
from vqapr.models.contexts import StrategyModelContext
from vqapr.models.memory import normalize_memory
from vqapr.models.strategy_model import NoDecision, StrategyModel
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    IntentSourceRef,
    validate_economic_intent,
)
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.runtime.events import DueExecutionEnvelope, OperationEnvelope
from vqapr.valuation.configuration import ValuationConfig
from vqapr.valuation.marking import SelectedMark, ValuationService
from vqapr.valuation.marks import MarkBatch


def _source_digest(path: Path) -> str:
    """Hash the bytes available to a callback; this is provenance, not a byte freeze."""
    files = (path,) if path.is_file() else tuple(sorted(path.glob("**/*.parquet")))
    if not files:
        raise ValueError(f"source path has no readable parquet bytes: {path}")
    digest = hashlib.sha256()
    for file_path in files:
        with file_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


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
class DueExecutionTrace:
    due: DueExecutionEnvelope
    result: DueExecutionResult
    state: AcceptedRunState


@dataclass(frozen=True, slots=True)
class SimulationResult:
    occurrences: tuple[OccurrenceTrace | DueExecutionTrace, ...]
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
class PlanningEvidence:
    """Execution-time economic inputs checked before submitting orders."""

    nav: Decimal
    cash_target: Decimal
    source_refs: tuple[IntentSourceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.nav, Decimal) or not self.nav.is_finite() or self.nav <= 0:
            raise ValueError("nav must be a positive finite Decimal")
        if not isinstance(self.cash_target, Decimal) or not self.cash_target.is_finite():
            raise ValueError("cash_target must be a finite Decimal")
        if not isinstance(self.source_refs, tuple) or not all(
            isinstance(source, IntentSourceRef) for source in self.source_refs
        ):
            raise TypeError("source_refs must be a tuple of IntentSourceRef values")


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
            [ValuationConfig, datetime, AccountSnapshot],
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
        if not constraints:
            raise ValueError("SimulationFlow requires one shared non-empty constraint set")
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
        initial = state.current.account
        if not isinstance(initial, AccountState):
            raise ValueError("state must begin with the frozen AccountState root")
        if frozen_run.initial_account_snapshot != initial.snapshot:
            raise ValueError("state AccountState must match FrozenRun initial account snapshot")
        if frozen_run.initial_account_mode != account.mode:
            raise ValueError("Account mode must match FrozenRun initial account mode")

    def run(self) -> SimulationResult:
        """Synchronously process the static merge and all due items in its horizon."""
        current_ref = self._state.current.current_model_state_ref
        if current_ref is None:
            raise RuntimeError("run state has no current Strategy root")
        self._strategy.memory = self._state.load_model_state(current_ref)
        self._strategy.load_payload(BytesIO(self._state.load_payload(current_ref)))
        traces: list[OccurrenceTrace | DueExecutionTrace] = []
        static = iter(OperationEnvelope(item) for item in self._frozen_run.static_occurrences)
        next_static = next(static, None)

        while next_static is not None or self._pending_due() is not None:
            due = self._pending_due()
            if due is not None and (
                next_static is None or due.sort_key() <= next_static.sort_key()
            ):
                traces.append(
                    self._guard(
                        "simulation.due",
                        due.due_time,
                        lambda due=due: self._dispatch_due(due),
                    )
                )
                continue
            assert next_static is not None
            occurrence = next_static.occurrence
            next_static = next(static, None)
            if occurrence.role is OperationRole.STRATEGY_CALLBACK:
                traces.append(
                    self._guard(
                        "simulation.callback",
                        occurrence.evaluation_time,
                        lambda occurrence=occurrence: self._dispatch_callback(occurrence),
                    )
                )
            elif occurrence.role is OperationRole.VALUATION:
                traces.append(
                    self._guard(
                        "simulation.valuation",
                        occurrence.evaluation_time,
                        lambda occurrence=occurrence: self._dispatch_valuation(occurrence),
                    )
                )
            elif occurrence.role is OperationRole.MONITORING:
                traces.append(
                    self._guard(
                        "simulation.monitoring",
                        occurrence.evaluation_time,
                        lambda occurrence=occurrence: self._dispatch_monitoring(occurrence),
                    )
                )
            else:  # OperationRole is closed, but keep malformed values fail-closed.
                raise ValueError(f"unsupported operation role: {occurrence.role!r}")

        if self._state.current.pending_accepted_intent is not None:
            raise RuntimeError("simulation finalized with a pending accepted intent")
        if self._frozen_run.end is None:
            raise RuntimeError("simulation finalization requires a frozen end")
        account = self._state.current.account
        finalization = FinalizationEvidence(
            stage="simulation.finalize",
            mutation=False,
            root_version=self._state.current.version,
            cutoff=self._frozen_run.end,
            account=None if account is None else account.snapshot,
        )
        root = self._guard(
            "simulation.finalize",
            self._frozen_run.end,
            lambda: self._state.finalize(RunFinalization(finalization)),
        )
        return SimulationResult(tuple(traces), root)

    def _guard(
        self,
        stage: str,
        cutoff: datetime,
        operation: Callable[[], object],
    ) -> object:
        try:
            return operation()
        except SimulationFailure:
            raise
        except Exception as error:
            root = self._state.current
            account = root.account
            pending = root.pending_accepted_intent
            raise SimulationFailure(
                stage=stage,
                cutoff=cutoff,
                root_version=root.version,
                account_version=None if account is None else account.snapshot.version,
                pending_id=getattr(pending, "pending_id", None),
                cause=error,
            ) from error

    def _pending_due(self) -> DueExecutionEnvelope | None:
        pending = self._state.current.pending_accepted_intent
        if pending is None:
            return None
        if not isinstance(pending, AcceptedIntent):
            raise TypeError("run state pending intent must be an AcceptedIntent")
        return DueExecutionEnvelope(pending.target.target_at, pending.pending_id)

    def _dispatch_due(self, due: DueExecutionEnvelope) -> DueExecutionTrace:
        pending = self._state.current.pending_accepted_intent
        if not isinstance(pending, AcceptedIntent) or pending.pending_id != due.pending_id:
            raise RuntimeError("pending intent changed while dispatching due execution")
        result = self._execute_due(pending)
        if self._state.current.pending_accepted_intent is not None:
            raise RuntimeError("due execution failed to consume its pending identity")
        return DueExecutionTrace(due, result, self._state.current)

    def _execute_due(self, pending: AcceptedIntent) -> DueExecutionResult:
        execution_input = self._frozen_run.execution_input
        if execution_input is None:
            raise RuntimeError("due execution requires frozen execution input")
        account_state = self._state.current.account
        if not isinstance(account_state, AccountState):
            raise RuntimeError("due execution requires an AccountState root")
        before = account_state.snapshot
        if pending.intent.strategy_id != str(self._frozen_run.strategy.component.component_id):
            raise ValueError(
                "pending intent strategy_id does not match the frozen Strategy component"
            )
        if pending.intent.account_version_seen != before.version:
            raise ValueError(
                "pending intent account_version_seen does not match current AccountSnapshot"
            )
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
            cash_target=pending.intent.cash_target,
            budget=pending.intent.budget,
        )
        fills = self._exchange.execute(orders, before, snapshot)
        prepared_fill = self._account.prepare_fill(
            account_state, fills, expected_version=before.version
        )
        selected_marks = self._marks_for_occurrence(
            self._frozen_run.valuation,
            pending.target.target_at,
            prepared_fill.next_snapshot,
        )
        mark = self._valuation_service.mark(prepared_fill.next_snapshot, selected_marks)
        prepared_account = self._account.prepare_mark(
            prepared_fill,
            mark,
            provenance=ValuationEvidence(
                stage="simulation.due.valuation",
                mutation=False,
                root_version=self._state.current.version,
                cutoff=pending.target.target_at,
                account=prepared_fill.next_snapshot,
                nav=prepared_fill.next_snapshot.cash + mark.total_value,
                marks=mark,
            ),
        )
        actual_constraints = evaluate_constraints(
            self._constraints, prepared_account.next_state.snapshot, mark
        )
        evidence = DueExecutionEvidence(
            stage="simulation.due",
            mutation=False,
            root_version=self._state.current.version,
            cutoff=pending.target.target_at,
            pending_id=pending.pending_id,
            before=before,
            after=prepared_account.next_state.snapshot,
            nav=prepared_account.next_state.latest_mark.nav,
            marks=mark,
            orders=orders,
            fills=fills,
            constraints=(
                actual_constraints,
                PlanningEvidence(nav, pending.intent.cash_target, pending.intent.source_refs),
            ),
        )
        root = self._state.complete_due(
            pending_id=pending.pending_id,
            account=prepared_account,
            fill=fills,
            mark=mark,
            feedback=(actual_constraints,),
            evidence=evidence,
        )
        assert root.account is not None
        return DueExecutionResult(pending.pending_id, root.account.snapshot.version, mark)

    def _dispatch_valuation(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("valuation requires an AccountState root")
        account = state.snapshot
        selected_marks = self._marks_for_occurrence(
            self._frozen_run.valuation,
            occurrence.evaluation_time,
            account,
        )
        marks = self._valuation_service.mark(account, selected_marks)
        valuation = ValuationResult(account, marks)
        return OccurrenceTrace(occurrence, valuation, self._state.current)

    def _dispatch_monitoring(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("monitoring requires an AccountState root")
        current = state.snapshot
        selected_marks = self._marks_for_occurrence(
            self._frozen_run.valuation,
            occurrence.evaluation_time,
            current,
        )
        marks = self._valuation_service.mark(current, selected_marks)
        valuation = ValuationResult(current, marks)
        report = evaluate_constraints(self._constraints, current, marks)
        return OccurrenceTrace(occurrence, MonitoringResult(valuation, report), self._state.current)

    def _dispatch_callback(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        current_ref = self._state.current.current_model_state_ref
        if current_ref is None:
            raise RuntimeError("callback requires a current Strategy root")
        before = self._state.load_model_state(current_ref)
        payload_before = self._state.load_payload(current_ref)
        previous_recorder = self._strategy.recorder
        try:
            self._strategy.memory = before
            self._strategy.load_payload(BytesIO(payload_before))
            window = self._window_for_occurrence(occurrence)
            if not isinstance(window, ModelWindow):
                raise TypeError("window_for_occurrence must return a ModelWindow")
            source_digests = self._source_digests_before_callback()
            state_account = self._state.current.account
            if not isinstance(state_account, AccountState):
                raise RuntimeError("callback requires an AccountState root")
            account = state_account.snapshot
            tables = self._strategy.tables()
            if not isinstance(tables, tuple) or not all(
                isinstance(table, TableSpec) for table in tables
            ):
                raise TypeError("StrategyModel.tables must return a tuple of TableSpec")
            recorder = InvocationRecorder(
                tables,
                run_id=self._frozen_run.identity,
                producer_id=str(self._frozen_run.strategy.component.component_id),
                stage=occurrence.role.value,
                event_time=occurrence.evaluation_time,
            )
            self._strategy.recorder = recorder
            projected = project_constraints(self._constraints, window)
            result = self._strategy.on_occurrence(
                StrategyModelContext(
                    occurrence=occurrence,
                    window=window,
                    account=account,
                    constraint_bounds=merged_constraint_bounds(projected),
                )
            )
            candidate = normalize_memory(self._strategy.memory)
            payload_candidate = BytesIO()
            self._strategy.save_payload(payload_candidate)
            if isinstance(result, NoDecision):
                evidence = CallbackEvidence(
                    stage="simulation.callback",
                    mutation=False,
                    root_version=self._state.current.version,
                    cutoff=occurrence.evaluation_time,
                    account=account,
                    pending_id=None,
                    decision=result,
                    constraints=projected,
                )
                root = self._state.publish(
                    self._state.prepare_callback(
                        candidate,
                        payload_candidate.getvalue(),
                        lifecycle=LifecycleTrace(LifecycleKind.NO_DECISION, evidence),
                        recorder=recorder,
                    )
                )
            else:
                intent = validate_economic_intent(result)
                self._validate_intent_authority(intent, account, window, source_digests)
                intended = validate_intended_constraints(self._constraints, intent, projected)
                if any(not item.finding.passed for item in intended):
                    raise ValueError("economic intent violates projected constraints")
                accepted = self._accept_intent(intent, occurrence)
                evidence = CallbackEvidence(
                    stage="simulation.callback",
                    mutation=False,
                    root_version=self._state.current.version,
                    cutoff=occurrence.evaluation_time,
                    account=account,
                    pending_id=accepted.pending_id,
                    decision=accepted,
                    constraints=(*projected, *intended),
                )
                root = self._state.publish(
                    self._state.prepare_callback(
                        candidate,
                        payload_candidate.getvalue(),
                        lifecycle=LifecycleTrace(LifecycleKind.ACCEPTED_INTENT, evidence),
                        recorder=recorder,
                        pending_accepted_intent=accepted,
                    )
                )
        except Exception:
            self._strategy.memory = before
            self._strategy.load_payload(BytesIO(payload_before))
            raise
        finally:
            self._strategy.recorder = previous_recorder
        if root.current_model_state_ref is None:
            raise RuntimeError("successful callback did not commit model state")
        self._strategy.memory = root.load_model_state(root.current_model_state_ref)
        self._strategy.load_payload(BytesIO(root.load_payload(root.current_model_state_ref)))
        return OccurrenceTrace(occurrence, result, root)

    def _validate_intent_authority(
        self,
        intent: EconomicPortfolioIntent,
        account: AccountSnapshot,
        window: ModelWindow,
        source_digests: Mapping[str, str],
    ) -> None:
        if intent.strategy_id != str(self._frozen_run.strategy.component.component_id):
            raise ValueError("intent strategy_id does not match the frozen Strategy component")
        if (
            intent.model_state_ref is not None
            and intent.model_state_ref != self._state.current.current_model_state_ref
        ):
            raise ValueError("intent model_state_ref does not match the visible prior model state")
        if intent.account_version_seen != account.version:
            raise ValueError("intent account_version_seen does not match current AccountSnapshot")
        actual_refs = self._actual_source_refs(window, source_digests)
        if intent.source_refs != actual_refs:
            raise ValueError(
                "intent source_refs do not exactly match sources read through ModelWindow"
            )

    def _source_digests_before_callback(self) -> dict[str, str]:
        """Capture source bytes immediately before Strategy reads them, without freezing bytes."""
        return {
            str(source.source_id): _source_digest(source.path)
            for source in self._frozen_run.sources
        }

    def _actual_source_refs(
        self, window: ModelWindow, source_digests: Mapping[str, str]
    ) -> tuple[IntentSourceRef, ...]:
        datasets = {str(dataset.dataset_id): dataset for dataset in self._frozen_run.datasets}
        sources = {str(source.source_id): source for source in self._frozen_run.sources}
        source_ids: list[str] = []
        for access in window.accesses:
            dataset = datasets.get(str(access.dataset_id))
            if dataset is None:
                raise ValueError("ModelWindow read a dataset absent from the FrozenRun")
            source_id = str(dataset.source)
            if source_id not in sources:
                raise ValueError(
                    "FrozenRun dataset source is absent from frozen source declarations"
                )
            if source_id not in source_digests:
                raise RuntimeError("missing source digest for ModelWindow access")
            if source_id not in source_ids:
                source_ids.append(source_id)
        return tuple(
            IntentSourceRef(source_id, source_digests[source_id]) for source_id in source_ids
        )

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
