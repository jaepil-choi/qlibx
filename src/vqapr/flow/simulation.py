"""Frequency-agnostic deterministic dispatcher for one frozen simulation run."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid5

from vqapr.account.account import Account
from vqapr.account.history import AccountHistory, AccountRequirement
from vqapr.account.snapshot import AccountMark, AccountSnapshot, AccountState
from vqapr.constraints.constraint import Constraint
from vqapr.constraints.evaluation import (
    evaluate_constraints,
    merged_constraint_bounds,
    project_constraints,
    validate_intended_constraints,
)
from vqapr.constraints.findings import ConstraintReport
from vqapr.data.lookback import RowsLookback
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.evidence.artifacts import (
    AccountCommitEvidence,
    CallbackEvidence,
    DueExecutionEvidence,
    FailureObservation,
    FeedbackEvidence,
    FinalizationEvidence,
    MarkEvidence,
    MonitoringEvidence,
    RetryPrecondition,
    SimulationFailure,
    SimulationFailureFamily,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.conventions import ExactExecutionTarget, ExecutionHorizon
from vqapr.exchange.execution_table import exact_execution_snapshot
from vqapr.exchange.venue import Exchange
from vqapr.flow.model_state import prepare_model_state
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


def _marks_from_execution_snapshot(
    snapshot: object,
    target_at: datetime,
    *,
    previous: AccountMark | None = None,
    held: Mapping[str, Decimal] | None = None,
) -> tuple[SelectedMark, ...]:
    """Value the book from the prices the venue published as executable at this instant.

    A row with a price marks the name, **including when `is_tradable` is false**: the venue
    published a price, and refusing to trade is a different fact from refusing to quote.

    A name the venue published nothing for **carries its previous mark forward, keeping the
    instant that mark was originally observed at**. A halt is not a reason to write a holding
    down, and it is not a reason to drop it out of NAV either; it is a reason for its price to
    stop moving. `SelectedMark.staleness(cutoff)` is what makes the gap visible afterwards.

    A name with no row and no previous mark produces nothing. That is a position the venue has
    never priced, so there is no honest number to put in the denominator.
    """
    marks: dict[str, SelectedMark] = {}
    for row in getattr(snapshot, "rows", ()):
        price = row.price
        if price is None or price <= 0:
            continue
        marks[row.instrument] = SelectedMark(row.instrument, price, target_at)
    if previous is not None and held is not None:
        for carried in previous.marks.marks:
            if carried.instrument_id in marks or carried.instrument_id not in held:
                continue
            observed_at = _observed_at(previous, carried.instrument_id)
            if observed_at is None:
                continue
            marks[carried.instrument_id] = SelectedMark(
                carried.instrument_id, carried.price, observed_at
            )
    return tuple(marks[instrument] for instrument in sorted(marks))


def _observed_at(mark: AccountMark, instrument: str) -> datetime | None:
    """When the carried price was actually observed, not when it was carried.

    A mark taken before this design carries no instant; it cannot claim one retroactively.
    """
    selected = mark.observed_at_by_instrument
    if selected is not None:
        return selected.get(instrument, mark.marked_at)
    return mark.marked_at


@dataclass(frozen=True, slots=True)
class PendingValuation:
    """An occurrence that requested no orders but still values the book.

    A `NoDecision` is not "nothing happened". The venue still publishes prices at the execution
    instant, and the book is still worth something there. This carries the selected target so the
    occurrence reaches the execution snapshot, without carrying an intent -- an empty
    `EconomicPortfolioIntent` would mean "hold no positions", which is the opposite of holding.
    """

    occurrence: OperationOccurrence
    decision_time: datetime
    target: ExactExecutionTarget
    valuation_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")
        if self.decision_time != self.occurrence.evaluation_time:
            raise ValueError("decision_time must be the current occurrence evaluation_time")
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if not isinstance(self.target, ExactExecutionTarget):
            raise TypeError("target must be an ExactExecutionTarget")
        if self.target.target_at.astimezone(UTC) <= self.decision_time.astimezone(UTC):
            raise ValueError("execution target must be strictly later than decision_time")

    @property
    def pending_id(self) -> str:
        return str(self.valuation_id)


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


def callback_evidence(result: SimulationResult) -> tuple[CallbackEvidence, ...]:
    """Every Strategy callback evidence a finished run published, in lifecycle order.

    A run's decisions are reachable only through its state root, and reconstructing them from
    ``occurrences`` would mean re-deriving what the Flow already stamped. This is the read half of
    the publication contract: what ``publish_run_allocation`` consumes, taken from where the Flow
    put it. Declining callbacks are included, because whether a decline publishes nothing is the
    publisher's rule to apply, not this accessor's.
    """
    if not isinstance(result, SimulationResult):
        raise TypeError("result must be a SimulationResult returned by run()")
    return tuple(
        trace.detail
        for trace in result.final_state.lifecycle_trace
        if isinstance(trace.detail, CallbackEvidence)
    )


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


class FailedAfterCommit(SimulationFailure):
    """A due-chain failure after the Account authority has advanced."""


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
    evidence: ValuationEvidence

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
    evidence: MonitoringEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.valuation, ValuationResult):
            raise TypeError("valuation must be a ValuationResult")
        if not isinstance(self.report, ConstraintReport):
            raise TypeError("report must be a ConstraintReport")
        if self.report.account_version != self.valuation.account.version:
            raise ValueError("report must evaluate the marked account version")


def _shadows_package_table(table_id: str) -> bool:
    """Whether a declared table id lays claim to the package's reserved namespace.

    Comparison is normalised because a raw ``startswith`` is trivially defeated. A plain
    case-sensitive check let ``VQAPR.account`` and a leading-space `` vqapr.account`` through;
    adding ``casefold`` alone still let the full-width rendering and zero-width insertions through.
    In every case the spoofed table sat beside the real one in the same recorder under a distinct
    key, and a reader had no way to tell which was authoritative -- which is precisely what the
    reservation exists to prevent.

    Only *visible* disguises are this function's problem. Invisible characters are refused where a
    `TableSpec` is built, so by the time an id reaches here it cannot contain one. What remains is
    the class of spellings that look like the prefix and fold onto it -- the full-width rendering,
    mathematical alphanumerics, case variants -- which compatibility folding and case folding catch.

    It does not chase homoglyphs from other scripts: a Cyrillic lookalike is a different string by
    any normalisation, and defeating it needs a confusables skeleton, which is disproportionate for
    a namespace guard and would start rejecting legitimate non-Latin ids.
    """
    folded = unicodedata.normalize("NFKC", table_id).strip().casefold()
    return folded.startswith(DEFAULT_TABLE_PREFIX)


_VALUATION_NAMESPACE = UUID("3f1c9a7e-1d4b-4f52-9c8a-6b2e7d0a5f31")
"""Namespace for the pending identity a no-order occurrence carries into execution."""

_ACCOUNT_IDENTITY = "_ACCOUNT"
"""Synthetic instrument identity for the account-level series (canon 11.2 precedent)."""

DEFAULT_TABLE_PREFIX = "vqapr."
"""Table ids the package owns. A Strategy declaring one is refused when the recorder is built."""

DEFAULT_TABLES = (
    TableSpec(f"{DEFAULT_TABLE_PREFIX}weight", ("instrument", "weight")),
    TableSpec(
        f"{DEFAULT_TABLE_PREFIX}account",
        ("instrument", "cash", "nav", "quantity", "price", "observed_at", "account_version"),
    ),
    TableSpec(
        f"{DEFAULT_TABLE_PREFIX}fill",
        (
            "instrument",
            "account_version",
            "requested_quantity",
            "dealt_quantity",
            "price",
            "cash_delta",
            "commission",
            "tax",
            "reason",
        ),
    ),
)
"""What every run records without the Strategy asking.

Canon 9.2 makes these defaults rather than opt-in because both are package-computed -- the weights
from the accepted intent, the account state from the committed Account. Requiring a declaration
would make a package fact contingent on user opt-in.

**This is decision-time state, not a performance series.** A callback sees an `AccountSnapshot`,
which carries version, cash and positions but no marks: marking happens on the due-execution path,
so at callback time there is no NAV to copy. Recording cash under the name NAV would put a wrong
number under a true-sounding name, which is worse than recording nothing. The NAV series canon 5.2
requires -- stamped at its mark instant -- needs a recorder where marks exist, and is a named
follow-up rather than something this table quietly approximates.
"""


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
        strategy_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        constraint_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        account: Account,
        exchange: Exchange,
        constraints: tuple[Constraint, ...],
        valuation_service: ValuationService | None = None,
    ) -> None:
        if not isinstance(frozen_run, FrozenRun):
            raise TypeError("frozen_run must be a FrozenRun")
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
        declared = frozen_run.constraints.constraints
        if len(constraints) != len(declared):
            raise ValueError("loaded constraints must exactly match FrozenRun ConstraintSet")
        if tuple(constraint.constraint_id for constraint in constraints) != tuple(
            str(component.component_id) for component in declared
        ):
            raise ValueError("loaded constraints must preserve FrozenRun ConstraintSet identity")
        if valuation_service is not None and not isinstance(valuation_service, ValuationService):
            raise TypeError("valuation_service must be a ValuationService or None")
        self._frozen_run = frozen_run
        self._strategy = strategy
        self._state = state
        self._strategy_window_for_occurrence = strategy_window_for_occurrence
        self._constraint_window_for_occurrence = constraint_window_for_occurrence
        self._account = account
        self._exchange = exchange
        self._constraints = constraints
        self._valuation_service = valuation_service or ValuationService()
        declared = tuple(getattr(strategy, "account_requirements", tuple)())
        if any(not isinstance(item, AccountRequirement) for item in declared):
            raise TypeError("account_requirements must return AccountRequirement values")
        if len({item.consumer_id for item in declared}) != len(declared):
            raise ValueError("account requirements must not repeat a consumer_id")
        # One projection per callback, so a single merged declaration is what the run reads and
        # what it retains. Separate consumers would each need their own window; there is one.
        self._account_requirement = (
            AccountRequirement(
                "strategy",
                tuple(dict.fromkeys(field for item in declared for field in item.fields)),
                RowsLookback(max(item.lookback.rows for item in declared)),
            )
            if declared
            else None
        )
        self._horizon: ExecutionHorizon | None = None
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
        cutoff = self._frozen_run.start or self._frozen_run.end
        if cutoff is None:
            raise RuntimeError("simulation start requires a frozen boundary")
        self._guard(
            SimulationStage.START,
            cutoff,
            self._load_visible_strategy_state,
            family=SimulationFailureFamily.DATA,
            owner=self._frozen_run.strategy,
        )
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
                        SimulationStage.DUE_SNAPSHOT,
                        due.due_time,
                        lambda due=due: self._dispatch_due(due),
                        family=SimulationFailureFamily.DATA,
                        owner=self._frozen_run.execution_input,
                    )
                )
                continue
            assert next_static is not None
            occurrence = next_static.occurrence
            next_static = next(static, None)
            if occurrence.role is OperationRole.STRATEGY_CALLBACK:
                traces.append(self._dispatch_callback(occurrence))
            elif occurrence.role is OperationRole.VALUATION:
                traces.append(
                    self._guard(
                        SimulationStage.VALUATION,
                        occurrence.evaluation_time,
                        lambda occurrence=occurrence: self._dispatch_valuation(occurrence),
                        family=SimulationFailureFamily.VALUATION,
                        owner=self._frozen_run.valuation,
                    )
                )
            elif occurrence.role is OperationRole.MONITORING:
                traces.append(
                    self._guard(
                        SimulationStage.MONITORING,
                        occurrence.evaluation_time,
                        lambda occurrence=occurrence: self._dispatch_monitoring(occurrence),
                        family=SimulationFailureFamily.VALUATION,
                        owner=self._frozen_run.monitoring_agenda,
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
            run_identity=self._frozen_run.identity,
            strategy_agenda=self._frozen_run.strategy_agenda,
            valuation_agenda=self._frozen_run.valuation_agenda,
            monitoring_agenda=self._frozen_run.monitoring_agenda,
            root_version=self._state.current.version,
            cutoff=self._frozen_run.end,
            account=None if account is None else account.snapshot,
        )
        root = self._guard(
            SimulationStage.FINALIZE,
            self._frozen_run.end,
            lambda: self._state.finalize(RunFinalization(finalization)),
            family=SimulationFailureFamily.FINALIZATION,
            owner=finalization,
        )
        return SimulationResult(tuple(traces), root)

    def _guard(
        self,
        stage: SimulationStage,
        cutoff: datetime,
        operation: Callable[[], object],
        *,
        family: SimulationFailureFamily,
        owner: object,
    ) -> object:
        try:
            return operation()
        except SimulationFailure:
            raise
        except Exception as error:
            raise self._failure(
                stage=stage,
                cutoff=cutoff,
                owner=owner,
                family=family,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error

    def _failure(
        self,
        *,
        stage: SimulationStage,
        cutoff: datetime,
        owner: object,
        family: SimulationFailureFamily,
        cause: Exception,
        kind: SimulationFailureKind,
    ) -> SimulationFailure:
        root = self._state.current
        account = root.account
        pending = root.pending_accepted_intent
        failed_requirement: object = owner
        if isinstance(cause, VqaprError):
            family = SimulationFailureFamily(cause.family.value)
            failed_requirement = cause.failures[0] if len(cause.failures) == 1 else cause.failures
        failure_type = (
            FailedAfterCommit
            if kind is SimulationFailureKind.FAILED_AFTER_COMMIT
            else SimulationFailure
        )
        return failure_type(
            family=family,
            stage=stage,
            clock=cutoff,
            failed_requirement=failed_requirement,
            observed=FailureObservation(type(cause), tuple(cause.args)),
            retry_precondition=RetryPrecondition(
                requires_replay_from_root=True,
                required_pending_id=getattr(pending, "pending_id", None),
            ),
            correlation_id=self._frozen_run.identity,
            frozen_run_identity=self._frozen_run.identity,
            cutoff=cutoff,
            root_version=root.version,
            model_version=root.model_state_commit_count,
            model_state_ref=root.current_model_state_ref,
            account_version=None if account is None else account.snapshot.version,
            pending_id=getattr(pending, "pending_id", None),
            cause=cause,
            kind=kind,
        )

    def _due_boundary(
        self,
        *,
        stage: SimulationStage,
        cutoff: datetime,
        owner: object,
        family: SimulationFailureFamily,
        kind: SimulationFailureKind,
        operation: Callable[[], object],
    ) -> object:
        try:
            return operation()
        except SimulationFailure:
            raise
        except Exception as error:
            raise self._failure(
                stage=stage,
                cutoff=cutoff,
                owner=owner,
                family=family,
                cause=error,
                kind=kind,
            ) from error

    def _pending_due(self) -> DueExecutionEnvelope | None:
        pending = self._state.current.pending_accepted_intent
        if pending is None:
            return None
        if not isinstance(pending, (AcceptedIntent, PendingValuation)):
            raise TypeError("run state pending must be an AcceptedIntent or PendingValuation")
        return DueExecutionEnvelope(pending.target.target_at, pending.pending_id)

    def _dispatch_due(self, due: DueExecutionEnvelope) -> DueExecutionTrace:
        pending = self._state.current.pending_accepted_intent
        if (
            not isinstance(pending, (AcceptedIntent, PendingValuation))
            or pending.pending_id != due.pending_id
        ):
            raise RuntimeError("pending intent changed while dispatching due execution")
        if isinstance(pending, PendingValuation):
            result: object = self._value_due(pending)
        else:
            result = self._execute_due(pending)
        if self._state.current.pending_accepted_intent is not None:
            raise RuntimeError("due execution failed to consume its pending identity")
        return DueExecutionTrace(due, result, self._state.current)

    def _value_due(self, pending: PendingValuation) -> object:
        """Value the book at an execution instant that carried no orders.

        Same instant, same snapshot, same prices an order would have been filled at -- only
        without an order. The Account is not changed, so no version is consumed.
        """
        execution_input = self._frozen_run.execution_input
        if execution_input is None:
            raise RuntimeError("due valuation requires frozen execution input")
        account_state = self._state.current.account
        if not isinstance(account_state, AccountState):
            raise RuntimeError("due valuation requires an AccountState root")
        before = account_state.snapshot
        held_instruments = tuple(before.positions)

        snapshot = self._due_boundary(
            stage=SimulationStage.DUE_SNAPSHOT,
            cutoff=pending.target.target_at,
            owner=execution_input,
            family=SimulationFailureFamily.DATA,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: exact_execution_snapshot(
                execution_input.table,
                target_at=pending.target.target_at,
                target_instruments=(),
                held_instruments=held_instruments,
                trade_price=pending.target.trade_price,
            ),
        )
        selected_marks = self._due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=pending.target.target_at,
            owner=self._frozen_run.valuation,
            family=SimulationFailureFamily.VALUATION,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: _marks_from_execution_snapshot(
                snapshot,
                pending.target.target_at,
                previous=account_state.latest_mark,
                held=before.positions,
            ),
        )
        mark = self._due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=pending.target.target_at,
            owner=self._frozen_run.valuation,
            family=SimulationFailureFamily.VALUATION,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._valuation_service.mark(before, selected_marks),
        )
        evidence = ValuationEvidence(
            run_identity=self._frozen_run.identity,
            agenda=self._frozen_run.strategy_agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            valuation_config=self._frozen_run.valuation,
            account=before,
            marks=mark,
            root_version=self._state.current.version,
            account_version=before.version,
        )
        prepared_account = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._account.prepare_valuation(
                account_state,
                mark,
                expected_version=before.version,
                provenance=evidence,
                marked_at=pending.target.target_at,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
            ),
        )
        prepared_root = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._state.prepare_valuation_only(
                pending_id=pending.pending_id,
                account=prepared_account,
                mark=mark,
                evidence=evidence,
            ),
        )
        self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._account.commit_valuation(prepared_account),
        )
        self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._state.publish_valuation_only(prepared_root),
        )
        return evidence

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

        def select_snapshot() -> object:
            # A held instrument absent from the table is a market fact, not a data-contract
            # breach: it delisted, or it has not listed yet. Canon 6.1 assigns that case to
            # zero-dealt evidence, and the Exchange publishes it as ABSENT. Refusing here would
            # end the run on the first delisting, which in a 3,000-name universe is the first
            # week.
            return exact_execution_snapshot(
                execution_input.table,
                target_at=pending.target.target_at,
                target_instruments=target_instruments,
                held_instruments=held_instruments,
                trade_price=pending.target.trade_price,
            )

        snapshot = self._due_boundary(
            stage=SimulationStage.DUE_SNAPSHOT,
            cutoff=pending.target.target_at,
            owner=execution_input,
            family=SimulationFailureFamily.DATA,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=select_snapshot,
        )
        prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
        selected_prices = {
            instrument: price for instrument, price in prices.items() if price is not None
        }
        # NAV values what can be priced at this instant. A holding with no row carries no
        # selected value, so it contributes nothing here and stays in the account untouched;
        # pricing it from a stale quote would put an invented number in the denominator every
        # later weight is converted against.
        nav = before.cash + sum(
            (
                before.positions[instrument] * selected_prices[instrument]
                for instrument in held_instruments
                if instrument in selected_prices
            ),
            Decimal("0"),
        )
        weights = {target.instrument_id: target.weight for target in targets}
        orders = self._due_boundary(
            stage=SimulationStage.DUE_ORDER_PLANNING,
            cutoff=pending.target.target_at,
            owner=pending.intent,
            family=SimulationFailureFamily.ORDER,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: plan_orders(
                account=before,
                execution_time_nav=nav,
                prices=selected_prices,
                weight_targets=weights,
                cash_target=pending.intent.cash_target,
                budget=pending.intent.budget,
                rules=self._exchange.rules.at(pending.target.target_at),
            ),
        )
        fills = self._due_boundary(
            stage=SimulationStage.DUE_EXCHANGE_EXECUTION,
            cutoff=pending.target.target_at,
            owner=self._frozen_run.exchange,
            family=SimulationFailureFamily.EXCHANGE,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._exchange.execute(orders, before, snapshot),
        )
        prepared_fill = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_PREPARATION,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._account.prepare_fill(
                account_state, fills, expected_version=before.version
            ),
        )
        commit_evidence = AccountCommitEvidence(
            run_identity=self._frozen_run.identity,
            agenda=self._frozen_run.strategy_agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            pending=pending,
            target=pending.target,
            fill_convention=execution_input.fill,
            execution_snapshot=snapshot,
            planning_nav=nav,
            planning_cash_target=pending.intent.cash_target,
            planning_budget=pending.intent.budget,
            intended_targets=pending.intent.targets,
            requested_orders=orders,
            dealt_fills=fills,
            before=before,
            committed=prepared_fill.next_snapshot,
            root_version=self._state.current.version,
            account_version_before=before.version,
            account_version_committed=prepared_fill.next_snapshot.version,
        )
        prepared_commit = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_PREPARATION,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._state.prepare_account_commit(
                pending_id=pending.pending_id,
                account=prepared_fill,
                fill=fills,
                evidence=commit_evidence,
            ),
        )
        self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_COMMIT,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.PRE_COMMIT,
            operation=lambda: self._account.commit_fill(prepared_fill),
        )
        committed_root = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_COMMIT,
            cutoff=pending.target.target_at,
            owner=account_state,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._publish_account_commit(prepared_commit),
        )
        selected_marks = self._due_boundary(
            stage=SimulationStage.DUE_VALUATION_SELECTION,
            cutoff=pending.target.target_at,
            owner=self._frozen_run.valuation,
            family=SimulationFailureFamily.VALUATION,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            # The venue already published these prices to fill against. Valuing the book at the
            # same instant from the same rows is what makes the mark and the fill agree.
            operation=lambda: _marks_from_execution_snapshot(
                snapshot,
                pending.target.target_at,
                previous=account_state.latest_mark,
                held=prepared_fill.next_snapshot.positions,
            ),
        )
        mark = self._due_boundary(
            stage=SimulationStage.DUE_VALUATION_MARK,
            cutoff=pending.target.target_at,
            owner=self._frozen_run.valuation,
            family=SimulationFailureFamily.VALUATION,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._valuation_service.mark(
                prepared_fill.next_snapshot, selected_marks
            ),
        )
        prepared_account = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._account.prepare_mark(
                prepared_fill,
                mark,
                marked_at=pending.target.target_at,
                observed_at={
                    selected.instrument_id: selected.observed_at for selected in selected_marks
                },
                provenance=ValuationEvidence(
                    run_identity=self._frozen_run.identity,
                    agenda=self._frozen_run.valuation_agenda,
                    occurrence=pending.occurrence,
                    root_version=committed_root.version,
                    cutoff=pending.target.target_at,
                    account=prepared_fill.next_snapshot,
                    marks=mark,
                    valuation_config=self._frozen_run.valuation,
                    account_version=prepared_fill.next_snapshot.version,
                ),
            ),
        )
        mark_evidence = MarkEvidence(
            run_identity=self._frozen_run.identity,
            agenda=self._frozen_run.valuation_agenda,
            occurrence=pending.occurrence,
            cutoff=pending.target.target_at,
            valuation_config=self._frozen_run.valuation,
            selected_marks=selected_marks,
            marks=mark,
            limitations=(),
            account=prepared_account.next_state.snapshot,
            root_version=committed_root.version,
            account_version=prepared_account.next_state.snapshot.version,
        )
        prepared_marked = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._state.prepare_marked(
                account=prepared_account,
                mark=mark,
                evidence=mark_evidence,
            ),
        )
        self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._account.commit_mark(prepared_account),
        )
        marked_root = self._due_boundary(
            stage=SimulationStage.DUE_ACCOUNT_MARK,
            cutoff=pending.target.target_at,
            owner=committed_root.account,
            family=SimulationFailureFamily.ACCOUNT,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._publish_marked(prepared_marked),
        )
        feedback_evidence = self._due_boundary(
            stage=SimulationStage.DUE_FEEDBACK_CANDIDATE,
            cutoff=pending.target.target_at,
            owner=pending,
            family=SimulationFailureFamily.PUBLICATION,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: FeedbackEvidence(
                run_identity=self._frozen_run.identity,
                agenda=self._frozen_run.strategy_agenda,
                occurrence=pending.occurrence,
                cutoff=pending.target.target_at,
                pending=pending,
                candidates=(fills, mark),
                root_version=marked_root.version,
                account_version=marked_root.account.snapshot.version,
            ),
        )
        due_evidence = DueExecutionEvidence(commit_evidence, mark_evidence, feedback_evidence)
        root = self._due_boundary(
            stage=SimulationStage.DUE_FEEDBACK_PUBLICATION,
            cutoff=pending.target.target_at,
            owner=feedback_evidence,
            family=SimulationFailureFamily.PUBLICATION,
            kind=SimulationFailureKind.FAILED_AFTER_COMMIT,
            operation=lambda: self._state.publish_feedback(
                self._state.prepare_feedback((due_evidence,), evidence=feedback_evidence)
            ),
        )
        assert root.account is not None
        return DueExecutionResult(pending.pending_id, root.account.snapshot.version, due_evidence)

    def _publish_account_commit(self, prepared: object) -> object:
        root = self._state.publish_account_commit(prepared)
        if root.account != self._account.state:
            raise RuntimeError("Account commit root does not mirror Account authority")
        return root

    def _publish_marked(self, prepared: object) -> object:
        root = self._state.publish_marked(prepared)
        if root.account != self._account.state:
            raise RuntimeError("Account mark root does not mirror Account authority")
        return root

    def _account_history(self) -> AccountHistory:
        """The Strategy's declared window onto marks the Account already committed.

        Bounded by the declaration, so this copies the declared window rather than the run so
        far. A Strategy that declared nothing gets an empty projection that refuses every read.
        """
        state = self._state.current.account
        marks = state.mark_history if isinstance(state, AccountState) else ()
        return AccountHistory(marks, self._account_requirement)

    def _committed_marks(self, state: AccountState) -> MarkBatch:
        """The valuation the Account already committed, or an empty one before the first mark.

        A run values its book where it executes. Between execution instants nothing about the
        valuation can have changed, because no new price has been published to change it.
        """
        latest = state.latest_mark
        if latest is None:
            return self._valuation_service.mark(state.snapshot, ())
        return latest.marks

    def _dispatch_valuation(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("valuation requires an AccountState root")
        account = state.snapshot
        # The book is valued where it is executed. A valuation occurrence reports the mark the
        # Account already committed at the most recent execution instant rather than deriving a
        # second valuation from a different price source, which would give one run two answers.
        marks = self._committed_marks(state)
        evidence = ValuationEvidence(
            run_identity=self._frozen_run.identity,
            agenda=self._frozen_run.valuation_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            valuation_config=self._frozen_run.valuation,
            account=account,
            marks=marks,
            root_version=self._state.current.version,
            account_version=account.version,
        )
        valuation = ValuationResult(account, marks, evidence)
        return OccurrenceTrace(occurrence, valuation, self._state.current)

    def _dispatch_monitoring(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("monitoring requires an AccountState root")
        current = state.snapshot
        window = None
        projected = ()
        if self._constraints:
            window = self._constraint_window_for_occurrence(occurrence)
            if not isinstance(window, ModelWindow):
                raise TypeError("constraint_window_for_occurrence must return a ModelWindow")
            projected = project_constraints(self._constraints, window)
        # Monitoring judges the account the run actually committed, so it reads the committed
        # mark rather than valuing the book a second time.
        marks = self._committed_marks(state)
        valuation_evidence = ValuationEvidence(
            run_identity=self._frozen_run.identity,
            agenda=self._frozen_run.monitoring_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            valuation_config=self._frozen_run.valuation,
            account=current,
            marks=marks,
            root_version=self._state.current.version,
            account_version=current.version,
        )
        valuation = ValuationResult(current, marks, valuation_evidence)
        report = evaluate_constraints(self._constraints, window, current, marks, projected)
        evidence = MonitoringEvidence(
            run_identity=self._frozen_run.identity,
            agenda=self._frozen_run.monitoring_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            account=current,
            valuation=valuation_evidence,
            report=report,
            root_version=self._state.current.version,
        )
        return OccurrenceTrace(
            occurrence, MonitoringResult(valuation, report, evidence), self._state.current
        )

    def _dispatch_callback(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        current_ref, before, payload_before = self._guard(
            SimulationStage.CALLBACK_STATE,
            occurrence.evaluation_time,
            self._visible_callback_state,
            family=SimulationFailureFamily.DATA,
            owner=self._frozen_run.strategy,
        )
        previous_recorder = self._strategy.recorder
        try:
            self._guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                lambda: self._restore_callback_state(before, payload_before),
                family=SimulationFailureFamily.DATA,
                owner=self._frozen_run.strategy,
            )
            window = self._guard(
                SimulationStage.CALLBACK_WINDOW,
                occurrence.evaluation_time,
                lambda: self._strategy_window(occurrence),
                family=SimulationFailureFamily.DATA,
                owner=self._frozen_run.strategy_requirements,
            )
            state_account = self._state.current.account
            if not isinstance(state_account, AccountState):
                self._guard(
                    SimulationStage.CALLBACK_STATE,
                    occurrence.evaluation_time,
                    lambda: self._raise_callback_account_state_error(),
                    family=SimulationFailureFamily.DATA,
                    owner=self._frozen_run.strategy,
                )
            account = state_account.snapshot
            recorder = self._callback_intent_boundary(
                occurrence,
                self._frozen_run.strategy,
                lambda: self._callback_recorder(occurrence),
            )
            self._guard(
                SimulationStage.CALLBACK_PUBLICATION,
                occurrence.evaluation_time,
                lambda: self._set_callback_recorder(recorder),
                family=SimulationFailureFamily.PUBLICATION,
                owner=recorder,
            )
            projected = ()
            if self._constraints:
                constraint_window = self._guard(
                    SimulationStage.CALLBACK_WINDOW,
                    occurrence.evaluation_time,
                    lambda: self._constraint_window(occurrence),
                    family=SimulationFailureFamily.DATA,
                    owner=self._frozen_run.constraint_requirements,
                )
                projected = tuple(
                    self._callback_intent_boundary(
                        occurrence,
                        constraint,
                        lambda constraint=constraint: project_constraints(
                            (constraint,), constraint_window
                        )[0],
                    )
                    for constraint in self._constraints
                )
            constraint_bounds = self._callback_intent_boundary(
                occurrence,
                projected,
                lambda: merged_constraint_bounds(projected),
            )
            result = self._callback_intent_boundary(
                occurrence,
                self._frozen_run.strategy,
                lambda: self._strategy.on_occurrence(
                    StrategyModelContext(
                        occurrence=occurrence,
                        window=window,
                        account=account,
                        constraint_bounds=constraint_bounds,
                        account_history=self._account_history(),
                    )
                ),
                data_owner=self._frozen_run.strategy_requirements,
            )
            pending_valuation: PendingValuation | None = None
            if isinstance(result, NoDecision):
                accepted: NoDecision | AcceptedIntent = result
                intended = ()
                # A NoDecision still reaches the execution instant, because the book is still
                # worth something there and the venue still publishes prices for it.
                pending_valuation = self._callback_intent_boundary(
                    occurrence,
                    self._frozen_run.execution_input,
                    lambda: self._accept_valuation(occurrence),
                )
            else:
                intent = self._callback_intent_boundary(
                    occurrence, result, lambda: validate_economic_intent(result)
                )
                self._callback_intent_boundary(
                    occurrence,
                    intent,
                    lambda: self._validate_intent_authority(intent, account, window),
                )
                intended = self._validate_callback_intended_constraints(
                    occurrence, intent, projected
                )
                if any(not item.finding.passed for item in intended):
                    failed = next(item for item in intended if not item.finding.passed)
                    constraint = next(
                        constraint
                        for constraint in self._constraints
                        if constraint.constraint_id == failed.constraint_id
                    )
                    self._callback_intent_boundary(
                        occurrence,
                        constraint,
                        lambda: self._raise_intended_constraint_failure(),
                    )
                accepted = self._callback_intent_boundary(
                    occurrence,
                    self._frozen_run.execution_input,
                    lambda: self._accept_intent(intent, occurrence),
                )
            # The package's own account of this occurrence, written without the Strategy asking.
            # Both values are package-computed, so recording them is a statement of what the run
            # did rather than a claim the Strategy made.
            self._record_defaults(recorder, accepted, account)
            candidate, payload_candidate, committed_ref = self._guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                lambda: self._candidate_callback_state(before, payload_before),
                family=SimulationFailureFamily.DATA,
                owner=self._frozen_run.strategy,
            )
            evidence, lifecycle = self._callback_intent_boundary(
                occurrence,
                accepted,
                lambda: self._callback_evidence(
                    occurrence,
                    account,
                    current_ref,
                    committed_ref,
                    window,
                    accepted,
                    projected,
                    intended,
                ),
            )
            prepared = self._guard(
                SimulationStage.CALLBACK_PUBLICATION,
                occurrence.evaluation_time,
                lambda: self._prepare_callback_publication(
                    candidate,
                    payload_candidate,
                    lifecycle,
                    recorder,
                    accepted,
                    pending_valuation,
                ),
                family=SimulationFailureFamily.PUBLICATION,
                owner=evidence,
            )
            root = self._guard(
                SimulationStage.CALLBACK_PUBLICATION,
                occurrence.evaluation_time,
                lambda: self._state.publish(prepared),
                family=SimulationFailureFamily.PUBLICATION,
                owner=prepared,
            )
        except Exception:
            self._guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                lambda: self._restore_callback_state(before, payload_before),
                family=SimulationFailureFamily.DATA,
                owner=self._frozen_run.strategy,
            )
            raise
        finally:
            self._strategy.recorder = previous_recorder
        return OccurrenceTrace(occurrence, result, root)

    def _load_visible_strategy_state(self) -> None:
        """Load the sole visible Strategy pair before any callback mutation."""
        current_ref = self._state.current.current_model_state_ref
        if current_ref is None:
            raise RuntimeError("run state has no current Strategy root")
        self._strategy.memory = self._state.load_model_state(current_ref)
        self._strategy.load_payload(BytesIO(self._state.load_payload(current_ref)))

    def _callback_intent_boundary(
        self,
        occurrence: OperationOccurrence,
        owner: object,
        operation: Callable[[], object],
        *,
        data_owner: object | None = None,
    ) -> object:
        """Keep callback data-access failures out of the intent boundary."""
        try:
            return operation()
        except SimulationFailure:
            raise
        except VqaprError as error:
            family = SimulationFailureFamily(error.family.value)
            if family is SimulationFailureFamily.DATA:
                raise self._failure(
                    stage=SimulationStage.CALLBACK_WINDOW,
                    cutoff=occurrence.evaluation_time,
                    owner=self._frozen_run.strategy_requirements,
                    family=SimulationFailureFamily.DATA,
                    cause=error,
                    kind=SimulationFailureKind.PRE_COMMIT,
                ) from error
            raise self._failure(
                stage=SimulationStage.CALLBACK_INTENT,
                cutoff=occurrence.evaluation_time,
                owner=owner,
                family=SimulationFailureFamily.INTENT,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error
        except OSError as error:
            raise self._failure(
                stage=SimulationStage.CALLBACK_WINDOW,
                cutoff=occurrence.evaluation_time,
                owner=owner if data_owner is None else data_owner,
                family=SimulationFailureFamily.DATA,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error
        except Exception as error:
            raise self._failure(
                stage=SimulationStage.CALLBACK_INTENT,
                cutoff=occurrence.evaluation_time,
                owner=owner,
                family=SimulationFailureFamily.INTENT,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error

    def _prepare_callback_publication(
        self,
        memory: object,
        payload: bytes,
        lifecycle: LifecycleTrace,
        recorder: InvocationRecorder,
        accepted: NoDecision | AcceptedIntent,
        pending_valuation: PendingValuation | None = None,
    ) -> object:
        if isinstance(accepted, NoDecision):
            if pending_valuation is None:
                # Nothing to take: leave whatever the root already had pending untouched.
                return self._state.prepare_callback(
                    memory,
                    payload,
                    lifecycle=lifecycle,
                    recorder=recorder,
                )
            # A NoDecision still carries a pending identity when an execution instant remains,
            # so the occurrence reaches the venue's prices and values the book there.
            return self._state.prepare_callback(
                memory,
                payload,
                lifecycle=lifecycle,
                recorder=recorder,
                pending_accepted_intent=pending_valuation,
            )
        return self._state.prepare_callback(
            memory,
            payload,
            lifecycle=lifecycle,
            recorder=recorder,
            pending_accepted_intent=accepted,
        )

    def _restore_callback_state(self, memory: object, payload: bytes) -> None:
        self._strategy.memory = memory
        self._strategy.load_payload(BytesIO(payload))

    def _record_defaults(
        self,
        recorder: InvocationRecorder,
        accepted: object,
        account: AccountSnapshot,
    ) -> None:
        """Write the package-owned tables for one occurrence.

        A declining occurrence still records its account state: that the Strategy chose not to act
        is itself part of what a later run needs to reuse this one.
        """
        intent = getattr(accepted, "intent", accepted)
        for target in getattr(intent, "targets", ()):
            weight = getattr(target, "weight", None)
            if weight is None:
                continue
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}weight",
                {"instrument": target.instrument_id, "weight": str(weight)},
            )
        # The account's own record, published rather than retained. A run keeps only the marks
        # somebody declared they would read (canon 7.3), so this table -- not memory -- is what a
        # later reader reconstructs the run's valuation from. Recording the *committed* mark, not
        # a live one, is why the series is offset one commit behind the callback that writes it:
        # a callback reports the account it saw before deciding.
        mark = self._committed_mark()
        prices = {} if mark is None else {m.instrument_id: m for m in mark.marks.marks}
        observed = {} if mark is None else (mark.observed_at_by_instrument or {})
        recorder.append(
            f"{DEFAULT_TABLE_PREFIX}account",
            {
                # Account-level, so it carries the synthetic identity canon fixes for series with
                # no instrument axis rather than inventing a second key shape.
                "instrument": _ACCOUNT_IDENTITY,
                "cash": str(account.cash),
                "nav": None if mark is None else str(mark.nav),
                "quantity": None,
                "price": None,
                "observed_at": None,
                "account_version": account.version,
            },
        )
        for instrument in sorted(account.positions):
            valued = prices.get(instrument)
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}account",
                {
                    "instrument": instrument,
                    "cash": None,
                    "nav": None,
                    "quantity": str(account.positions[instrument]),
                    "price": None if valued is None else str(valued.price),
                    "observed_at": observed.get(instrument),
                    "account_version": account.version,
                },
            )

    def _committed_mark(self) -> object | None:
        state = self._state.current.account
        return state.latest_mark if isinstance(state, AccountState) else None

    def _set_callback_recorder(self, recorder: InvocationRecorder | None) -> None:
        self._strategy.recorder = recorder

    def _visible_callback_state(self) -> tuple[object, object, bytes]:
        current_ref = self._state.current.current_model_state_ref
        if current_ref is None:
            raise RuntimeError("callback requires a current Strategy root")
        return (
            current_ref,
            self._state.load_model_state(current_ref),
            self._state.load_payload(current_ref),
        )

    @staticmethod
    def _raise_callback_account_state_error() -> None:
        raise RuntimeError("callback requires an AccountState root")

    def _strategy_window(self, occurrence: OperationOccurrence) -> ModelWindow:
        window = self._strategy_window_for_occurrence(occurrence)
        if not isinstance(window, ModelWindow):
            raise TypeError("strategy_window_for_occurrence must return a ModelWindow")
        return window

    def _constraint_window(self, occurrence: OperationOccurrence) -> ModelWindow:
        window = self._constraint_window_for_occurrence(occurrence)
        if not isinstance(window, ModelWindow):
            raise TypeError("constraint_window_for_occurrence must return a ModelWindow")
        return window

    def _callback_recorder(self, occurrence: OperationOccurrence) -> InvocationRecorder:
        tables = self._strategy.tables()
        if not isinstance(tables, tuple) or not all(
            isinstance(table, TableSpec) for table in tables
        ):
            raise TypeError("StrategyModel.tables must return a tuple of TableSpec")
        declared = {table.table_id for table in tables}
        shadowed = sorted(name for name in declared if _shadows_package_table(name))
        if shadowed:
            # The prefix is reserved in canon so a Strategy cannot collide with or shadow a
            # package record. It fires while the recorder is built, before any row is written.
            raise ValueError(
                f"table ids beginning with {DEFAULT_TABLE_PREFIX!r} are package-owned: {shadowed}"
            )
        return InvocationRecorder(
            tables + DEFAULT_TABLES,
            run_id=self._frozen_run.identity,
            producer_id=str(self._frozen_run.strategy.component.component_id),
            stage=occurrence.role.value,
            event_time=occurrence.evaluation_time,
        )

    def _validate_callback_intended_constraints(
        self,
        occurrence: OperationOccurrence,
        intent: EconomicPortfolioIntent,
        projected: tuple[object, ...],
    ) -> tuple[object, ...]:
        projected_by_id = {item.constraint_id: item for item in projected}
        intended: list[object] = []
        for constraint in self._constraints:
            intended.extend(
                self._callback_intent_boundary(
                    occurrence,
                    constraint,
                    lambda constraint=constraint: validate_intended_constraints(
                        (constraint,),
                        intent,
                        (projected_by_id[constraint.constraint_id],),
                    ),
                )
            )
        return tuple(intended)

    def _candidate_callback_state(
        self, before: object, payload_before: bytes
    ) -> tuple[object, bytes, object]:
        candidate = normalize_memory(self._strategy.memory)
        payload_candidate = BytesIO()
        self._strategy.save_payload(payload_candidate)
        payload = payload_candidate.getvalue()
        committed_ref = prepare_model_state(candidate, payload).ref
        self._validate_candidate_payload(candidate, payload, before, payload_before)
        return candidate, payload, committed_ref

    def _callback_evidence(
        self,
        occurrence: OperationOccurrence,
        account: AccountSnapshot,
        current_ref: object,
        committed_ref: object,
        window: ModelWindow,
        accepted: NoDecision | AcceptedIntent,
        projected: tuple[object, ...],
        intended: tuple[object, ...],
    ) -> tuple[CallbackEvidence, LifecycleTrace]:
        evidence = CallbackEvidence(
            run_identity=self._frozen_run.identity,
            strategy=self._frozen_run.strategy,
            agenda=self._frozen_run.strategy_agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            root_version=self._state.current.version,
            account=account,
            current_model_state_ref=current_ref,
            committed_model_state_ref=committed_ref,
            strategy_accesses=window.accesses,
            actual_source_refs=self._callback_actual_source_refs(occurrence, window),
            decision=accepted,
            pending=None if isinstance(accepted, NoDecision) else accepted,
            constraints=(*projected, *intended),
        )
        lifecycle = LifecycleTrace(
            LifecycleKind.NO_DECISION
            if isinstance(accepted, NoDecision)
            else LifecycleKind.ACCEPTED_INTENT,
            evidence,
        )
        return evidence, lifecycle

    @staticmethod
    def _raise_intended_constraint_failure() -> None:
        raise ValueError("economic intent violates projected constraints")

    def _callback_actual_source_refs(
        self, occurrence: OperationOccurrence, window: ModelWindow
    ) -> tuple[IntentSourceRef, ...]:
        return self._guard(
            SimulationStage.CALLBACK_WINDOW,
            occurrence.evaluation_time,
            lambda: self._actual_source_refs(window),
            family=SimulationFailureFamily.DATA,
            owner=self._frozen_run.strategy_requirements,
        )

    def _validate_candidate_payload(
        self,
        candidate: object,
        payload_candidate: bytes,
        before: object,
        payload_before: bytes,
    ) -> None:
        """Prove the live Strategy can load and reproduce its candidate before root swap."""
        try:
            self._strategy.memory = normalize_memory(candidate)
            self._strategy.load_payload(BytesIO(payload_candidate))
            round_trip = BytesIO()
            self._strategy.save_payload(round_trip)
            if round_trip.getvalue() != payload_candidate:
                raise ValueError(
                    "StrategyModel payload load/save round-trip changed candidate bytes"
                )
            self._strategy.memory = normalize_memory(candidate)
        except Exception:
            self._strategy.memory = before
            self._strategy.load_payload(BytesIO(payload_before))
            raise

    def _validate_intent_authority(
        self,
        intent: EconomicPortfolioIntent,
        account: AccountSnapshot,
        window: ModelWindow,
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
        outside_universe = tuple(
            target.instrument_id
            for target in intent.targets
            if target.instrument_id not in self._frozen_run.instrument_set
        )
        if outside_universe:
            raise ValueError(
                f"intent targets are outside the frozen instrument universe: {outside_universe}"
            )
        actual_refs = self._actual_source_refs(window)
        if intent.source_refs != actual_refs:
            raise ValueError(
                "intent source_refs do not exactly match sources read through ModelWindow"
            )

    def _actual_source_refs(self, window: ModelWindow) -> tuple[IntentSourceRef, ...]:
        datasets = {str(dataset.dataset_id): dataset for dataset in self._frozen_run.datasets}
        sources = {str(source.source_id): source for source in self._frozen_run.sources}
        actual: dict[str, str] = {}
        for access in window.accesses:
            dataset = datasets.get(str(access.dataset_id))
            if dataset is None:
                raise ValueError("ModelWindow read a dataset absent from the FrozenRun")
            source_id = str(dataset.source)
            if source_id not in sources or access.source_id != source_id:
                raise ValueError(
                    "FrozenRun dataset source is absent from frozen source declarations"
                )
            previous = actual.setdefault(source_id, access.source_digest)
            if previous != access.source_digest:
                raise RuntimeError("one callback observed multiple byte digests for one source")
        return tuple(IntentSourceRef(source_id, digest) for source_id, digest in actual.items())

    def _execution_horizon(self, execution_input: object) -> ExecutionHorizon:
        """Read the run's candidate execution instants once, not once per callback.

        Built lazily so constructing a SimulationFlow still opens no physical source. The lower
        bound is the frozen run start, which no decision can precede.
        """
        if self._horizon is None:
            frozen = self._frozen_run
            if frozen.end is None:
                raise ValueError("an execution horizon requires a frozen run end")
            start = frozen.start
            if start is None:
                raise ValueError("an execution horizon requires a frozen run start")
            self._horizon = execution_input.fill.build_horizon(  # type: ignore[attr-defined]
                execution_input,
                start_time=start,
                end_time=frozen.end,
            )
        return self._horizon

    def _accept_valuation(self, occurrence: OperationOccurrence) -> PendingValuation | None:
        """Bind a no-order occurrence to the execution instant it would have traded at.

        Returns None when this occurrence must not take one, in which case the root's existing
        pending is left exactly as it was:

        - **An accepted intent is already pending.** It is waiting for its own due execution, and
          that execution will value the book. Replacing it here would silently discard a decision
          the Strategy already made and a fill that was going to happen.
        - **The run declared no execution authority.** A research run that only exercises
          callbacks never values against venue prices, so a NoDecision in it stays what it was.
        - **No execution instant remains in the horizon.** There is nothing left to value
          against, and a run ending on a NoDecision must still finalize.
        """
        if self._state.current.pending_accepted_intent is not None:
            return None
        frozen = self._frozen_run
        execution_input = frozen.execution_input
        if execution_input is None or frozen.end is None or frozen.start is None:
            # A run declared without execution authority never values against venue prices. That
            # is a legitimate configuration -- a research run that only exercises callbacks -- and
            # a NoDecision in it stays exactly what it was.
            return None
        target = execution_input.fill.select_target(
            execution_input,
            decision_time=occurrence.evaluation_time,
            end_time=self._frozen_run.end,
            horizon=self._execution_horizon(execution_input),
        )
        if target is None:
            return None
        return PendingValuation(
            occurrence=occurrence,
            decision_time=occurrence.evaluation_time,
            target=target,
            valuation_id=uuid5(
                _VALUATION_NAMESPACE,
                f"{self._frozen_run.identity}|{occurrence.evaluation_time.isoformat()}",
            ),
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
            horizon=self._execution_horizon(execution_input),
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
