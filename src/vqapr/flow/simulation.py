"""Frequency-agnostic deterministic dispatcher for one frozen simulation run."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from uuid import NAMESPACE_URL, UUID, uuid5

from vqapr.account.account import Account
from vqapr.account.history import AccountHistory
from vqapr.account.snapshot import AccountMark, AccountSnapshot, AccountState
from vqapr.authoring import AccountHistoryInput, EconomicAccountView, Hold, Rebalance
from vqapr.constraints.constraint import Constraint
from vqapr.constraints.evaluation import (
    build_account_view,
    evaluate_constraints,
    merged_constraint_bounds,
    project_constraints,
)
from vqapr.constraints.findings import ConstraintReport
from vqapr.data.windows import ModelWindow
from vqapr.domain.errors import ExplainTopic, Failure, FailureFamily, VqaprError
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
from vqapr.flow.run import FrozenRun, FrozenStrategy
from vqapr.flow.run_state import (
    AcceptedRunState,
    LifecycleKind,
    LifecycleTrace,
    RunFinalization,
    RunStateRepository,
)
from vqapr.models.contexts import StrategyModelContext
from vqapr.models.memory import normalize_memory
from vqapr.models.strategy_model import StrategyModel
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    IntentSourceRef,
    PortfolioTarget,
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

    A `Hold` is not "nothing happened". The venue still publishes prices at the execution
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
    # One row per declared constraint per monitoring occurrence: which rule, the limit it held
    # the book to, the value it measured, and the names that breached. PRD 7.1 asks a breach to
    # leave exactly those behind, and the `contract` block of the strategy record only ever
    # counted them -- `held` and `checked` say how often, not what or by how much.
    TableSpec(
        f"{DEFAULT_TABLE_PREFIX}monitoring",
        ("constraint", "passed", "measured", "bound", "excess", "offenders", "account_version"),
    ),

    TableSpec(
        f"{DEFAULT_TABLE_PREFIX}fill",
        (
            "instrument",
            # The category this fill was charged under. Declared here because the charge is a
            # lookup at fill time and nothing downstream can re-derive it; without the column the
            # value is computed and then dropped, and `cost_by_kind` has one unlabelled bucket.
            "kind",
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


def _require_constraint_identity(
    constraints: tuple[Constraint, ...], declared: tuple[object, ...]
) -> None:
    """Refuse an assembly whose loaded constraints are not the ones the run froze.

    Both halves were bare `ValueError`s, and a bare exception here has no structured body, so it
    surfaced as `stage: "unhandled"` with an empty `failures` list -- the framework announcing its
    own breakage when the real cause was a component registered under the wrong id.

    `load_constraint` refuses a mismatch at registration, so a constraint with a STABLE id can no
    longer reach here from the CLI. A constraint whose `constraint_id` is **volatile** — one that
    returns a different string on each access — still can, and does: it matches on the access
    `register` makes, matches again under `check`, and disagrees by the time the run is assembled.
    Red-teaming found exactly that, so this is a live gate rather than defence in depth, and it is
    the last place the disagreement can be caught.

    It says what it found because an invariant nobody can read is indistinguishable from a crash,
    which is the defect this whole change is about.
    """
    loaded_ids = tuple(constraint.constraint_id for constraint in constraints)
    declared_ids = tuple(str(component.component_id) for component in declared)
    if loaded_ids == declared_ids:
        return
    requirement = (
        "the constraints handed to a run must be exactly the ones its FrozenRun declared, "
        "in the same order and answering to the same ids"
    )
    observed = f"loaded {loaded_ids!r}, FrozenRun declared {declared_ids!r}"
    raise VqaprError(
        stage="run.assembly",
        family=FailureFamily.DATA,
        failures=[
            Failure.bounded(
                code="run.assembly.constraint_identity",
                requirement=requirement,
                observed=observed,
                fix=(
                    "register each Constraint under the id its own constraint_id returns, then "
                    "re-run; vqapr check reports this before a run is spent"
                ),
                explain=ExplainTopic.COMPONENT_CONTRACT,
            )
        ],
        mutation=False,
        retry_precondition="re-register the mismatched Constraint, then retry",
    )


def _raise_callback_return_type(returned: object) -> None:
    """Refuse a callback return that is not the decision algebra, naming what came back.

    `decide` returns `Hold | Rebalance` since record `125`, and until now nothing checked.
    A Strategy that returned a stamped `EconomicPortfolioIntent` -- the shape the contract used to
    take -- fell through every branch and surfaced as a complaint from inside constraint
    validation, three frames from the callback that caused it. Refusing here names the contract
    and the type that missed it.
    """
    raise TypeError(
        "decide must return Hold or Rebalance; got "
        f"{type(returned).__name__}. An intent's id, strategy, provenance and account version "
        "are stamped by the Flow (record 125), so a callback returns economics only"
    )


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
        layer: FrozenStrategy | None = None,
        strategy_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        constraint_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow],
        account: Account,
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
        self._frozen_run = frozen_run
        self._layer = layer
        self._static_occurrences = frozen_run.dispatch_order(layer)
        self._strategy = strategy
        self._state = state
        self._strategy_window_for_occurrence = strategy_window_for_occurrence
        self._constraint_window_for_occurrence = constraint_window_for_occurrence
        self._account = account
        self._exchange = exchange
        # The venue names the extra execution price its own regimes need, once per run. A venue
        # that declares none is read exactly as before.
        requirements = tuple(getattr(exchange, "execution_requirements", tuple)())
        prices = {requirement.price for requirement in requirements}
        if len(prices) > 1:
            raise ValueError("an Exchange may require at most one reference execution price")
        self._reference_price = next(iter(prices), None)
        self._constraints = constraints
        self._valuation_service = valuation_service or ValuationService()
        # The run already opens one duckdb handle for observations; the execution table was
        # opening and closing its own on every fill, which is where the time went.
        self._scan_session = scan_session
        self._on_progress = on_progress
        if not isinstance(record_account_positions, bool):
            raise TypeError("record_account_positions must be a bool")
        # Whether `vqapr.account` carries one row per held instrument at every valuation, or the
        # `_ACCOUNT` row alone. Declared in the run spec's `store:` block; the testbed's broad
        # signed book wrote 2.6M position rows of which the rows actually read were 0.07%.
        self._record_account_positions = record_account_positions
        # The project's instrument roster, bound into the venue's view at the one seam a category
        # enters through. Optional so a flow assembled without one still constructs; what it
        # cannot then do is answer what an instrument is, which it refuses rather than guesses.
        self._registry = registry
        # Bound onto the venue now, not per occurrence: `execute` reads the venue's own rules and
        # never receives one passed down, so binding only at the call site left every `Fill.kind`
        # null while a registered roster sat unused in the workspace.
        self._bind_registry_to_venue()
        declared = strategy.account_history()
        if declared is not None and not isinstance(declared, AccountHistoryInput):
            raise TypeError("account_history must return an AccountHistoryInput or None")
        # One declaration, one projection per callback: the run has one Strategy, and what it
        # declares is both what each callback reads and what the Account retains.
        self._account_history_declaration = declared
        self._horizon: ExecutionHorizon | None = None
        self._recorded_measurements: set[object] = set()
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
        cutoff = self._frozen_run.start or self._frozen_run.end
        if cutoff is None:
            raise RuntimeError("simulation start requires a frozen boundary")
        self._guard(
            SimulationStage.START,
            cutoff,
            self._load_visible_strategy_state,
            family=SimulationFailureFamily.DATA,
            owner=self._layer.config,
        )
        traces: list[OccurrenceTrace | DueExecutionTrace] = []
        static = iter(OperationEnvelope(item) for item in self._static_occurrences)
        next_static = next(static, None)

        while next_static is not None or self._pending_due() is not None:
            # One call per occurrence, for a caller that needs to prove it is still alive while
            # the run is executing. A run's only other outward sign is its result, which arrives
            # minutes later -- long after anything watching would have concluded it had died.
            if self._on_progress is not None:
                self._on_progress()
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
            strategy_agenda=self._layer.agenda,
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
                session=self._scan_session,
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
            agenda=self._layer.agenda,
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
        if pending.intent.strategy_id != str(self._layer.config.component.component_id):
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
                reference_price=self._reference_price,
                session=self._scan_session,
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
        # A halted row still carries a price, because a halt suspends trading and not valuation.
        # Planning has to know the difference or it funds buys from sales the venue will refuse.
        tradable = {row.instrument: row.is_tradable for row in snapshot.rows}
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
                rules=self._bound_rules(),
                tradable=tradable,
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
            agenda=self._layer.agenda,
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
                # The same five fields `InvocationRecorder` stamps on every other table. These
                # rows never pass through one, which is why they used to carry none of them.
                # `event_time` is when the fill happened -- the execution target -- not when the
                # decision that caused it was made.
                envelope={
                    "run_id": self._frozen_run.identity,
                    "producer_id": str(
                        self._layer.config.component.component_id
                    ),
                    "stage": pending.occurrence.role.value,
                    "event_time": pending.target.target_at,
                },
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
                agenda=self._layer.agenda,
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
        return AccountHistory(marks, self._account_history_declaration)

    def _committed_marks(self, state: AccountState) -> MarkBatch:
        """The valuation the Account already committed, or an empty one before the first mark.

        A run values its book where it executes. Between execution instants nothing about the
        valuation can have changed, because no new price has been published to change it.
        """
        latest = state.latest_mark
        if latest is None:
            return self._valuation_service.mark(state.snapshot, ())
        return latest.marks

    def _valuation_instant(self, occurrence: OperationOccurrence) -> datetime | None:
        """The execution instant a standalone valuation marks at, or `None` when none exists.

        Valuation resolution is (valuation clock) intersected with (execution `trade_at` set). The
        valuation clock says *when the run wants to know* what the book is worth; the execution
        table says *when the venue published a price* that could answer. Only their intersection
        is a moment where an honest number exists.

        This deliberately does not reuse `select_target`. That selects the first **strictly-later**
        eligible instant, which is right for an intent -- a decision cannot fill in a print that
        already happened -- and wrong here by exactly one instant: on the shipped cadence (decide
        08:00, fill 15:30, value 16:00) a 16:00 valuation would bind *tomorrow's* fill rather than
        the 15:30 close that just happened, stamping NAV one execution instant late along its
        entire length.
        """
        execution_input = self._frozen_run.execution_input
        if execution_input is None or self._frozen_run.end is None:
            # A run declared without execution authority never values against venue prices.
            return None
        return self._execution_horizon(execution_input).at_or_before(occurrence.evaluation_time)

    def _standalone_marks(
        self, state: AccountState, valuation_at: datetime
    ) -> tuple[SelectedMark, ...]:
        """Value the held book from the prices the venue published at `valuation_at`.

        This is the same mark path a due execution uses -- `exact_execution_snapshot` feeding
        `_marks_from_execution_snapshot` -- so a standalone valuation and a fill-time valuation
        cannot disagree about what a price means. Reaching that path was the whole point of the
        change; only the instant it is asked about is different.
        """
        execution_input = self._frozen_run.execution_input
        if execution_input is None:
            return ()
        held = state.snapshot.positions
        if not held:
            return ()
        snapshot = exact_execution_snapshot(
            execution_input.table,
            target_at=valuation_at,
            target_instruments=(),
            held_instruments=tuple(held),
            trade_price=execution_input.fill.trade_price,
            session=self._scan_session,
        )
        return _marks_from_execution_snapshot(
            snapshot,
            valuation_at,
            previous=state.latest_mark,
            held=held,
        )

    def _dispatch_valuation(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        state = self._state.current.account
        if not isinstance(state, AccountState):
            raise RuntimeError("valuation requires an AccountState root")
        account = state.snapshot
        # A valuation occurrence marks at its OWN instant. It used to replay whatever mark the
        # Account last committed, which made the NAV series inherit the decision cadence: a
        # monthly-rebalancing strategy reported a monthly NAV even though the venue published a
        # price every session and the book was worth something on every one of them.
        #
        # The pending slot is never touched here. `pending_accepted_intent` holds a single
        # occupant (`run_state.py:59`), so routing a daily valuation through it would overwrite
        # accepted decisions on most days. Marking synchronously sidesteps that entirely, which
        # is the decisive reason this is done here rather than through the pending lifecycle.
        valuation_at = self._valuation_instant(occurrence)
        if valuation_at is None:
            # The venue published no price at or before this instant, so no value exists. That is
            # a fact about the venue, not a failure, and it is reported as the empty mark rather
            # than as a stale number carried forward from somewhere else.
            selected: tuple[SelectedMark, ...] = ()
        else:
            selected = self._standalone_marks(state, valuation_at)
        marks = self._valuation_service.mark(account, selected)
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
        if self._standalone_valuation_adds_a_measurement(state, occurrence):
            self._commit_standalone_valuation(occurrence, state, marks, selected, evidence)
        return OccurrenceTrace(occurrence, valuation, self._state.current)

    def _standalone_valuation_adds_a_measurement(
        self, state: AccountState, occurrence: OperationOccurrence
    ) -> bool:
        """Whether this occurrence has something new to record, or the book is already valued.

        Mark history is strictly increasing in instant (`account/snapshot.py:118-122`), and it is
        that way because two marks at one instant are two answers to the same question. A fill
        already marks the book at its own execution instant, so a valuation occurrence landing on
        an instant already marked has nothing to add -- recording anyway would not merely
        duplicate a row, it would break the invariant.

        The value of the book is unchanged either way. What is skipped is a redundant restatement
        of it, not a measurement.
        """
        latest = state.latest_mark
        if latest is None or latest.marked_at is None:
            return True
        return occurrence.evaluation_time > latest.marked_at

    def _commit_standalone_valuation(
        self,
        occurrence: OperationOccurrence,
        state: AccountState,
        marks: MarkBatch,
        selected: tuple[SelectedMark, ...],
        evidence: ValuationEvidence,
    ) -> None:
        """Commit the mark and write the NAV it measured into the package's own account table.

        Marking without recording would leave the change invisible. `vqapr.account` is what a
        later reader reconstructs the series from (canon 7.3), and it was written **only** from
        the strategy-callback path, so the series resolution silently followed the DECISION clock:
        a monthly-rebalancing strategy left a monthly NAV series no matter how often the run
        valued the book. Recording here is what makes the valuation clock's independence
        observable rather than merely internal.

        The Account does not change -- there is no fill -- so this goes through the mark-only
        transition rather than an account commit, and the pending slot is still never touched.

        `observed_at` carries the instant each price was measured at, which is not the instant
        this row was written. Keeping them two columns is what lets a reader date the series by
        the measurement rather than by the occurrence; mislabelling one for the other was measured
        moving a factor correlation from 0.93 to 0.02.
        """
        observed_at = {mark.instrument_id: mark.observed_at for mark in selected}
        prepared_account = self._account.prepare_valuation(
            state,
            marks,
            expected_version=state.snapshot.version,
            provenance=evidence,
            marked_at=occurrence.evaluation_time,
            observed_at=observed_at,
        )
        mark = prepared_account.next_state.latest_mark
        account = state.snapshot

        recorder = InvocationRecorder(
            DEFAULT_TABLES,
            run_id=self._frozen_run.identity,
            producer_id=str(self._layer.config.component.component_id),
            stage=occurrence.role.value,
            event_time=occurrence.evaluation_time,
        )
        priced = {selection.instrument_id: selection for selection in selected}
        recorder.append(
            f"{DEFAULT_TABLE_PREFIX}account",
            {
                "instrument": _ACCOUNT_IDENTITY,
                # The values themselves, not their text: the run record writer records what
                # type each column was encoded from, so a reader gets a Decimal back.
                "cash": account.cash,
                "nav": mark.nav,
                "quantity": None,
                "price": None,
                "observed_at": mark.marked_at,
                "account_version": account.version,
            },
        )
        for instrument in sorted(account.positions) if self._record_account_positions else ():
            selection = priced.get(instrument)
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}account",
                {
                    "instrument": instrument,
                    "cash": None,
                    "nav": None,
                    "quantity": account.positions[instrument],
                    "price": None if selection is None else selection.price,
                    "observed_at": None if selection is None else selection.observed_at,
                    "account_version": account.version,
                },
            )

        self._account.commit_valuation(prepared_account)
        self._state.publish_standalone_valuation(
            self._state.prepare_standalone_valuation(
                account=prepared_account,
                mark=marks,
                recorder=recorder,
                evidence=evidence,
            )
        )
        # Recorded so a later callback does not write this same measurement a second time. Keyed
        # on the instant the mark was TAKEN rather than on this occurrence, because a callback
        # replays a committed mark and the two clocks differ -- comparing occurrences would never
        # match, and the duplicate would go out under a later `available_at`.
        recorded_at = getattr(mark, "marked_at", None)
        if recorded_at is not None:
            self._recorded_measurements.add(recorded_at)

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
        if report.findings:
            self._record_findings(occurrence, report)
        return OccurrenceTrace(
            occurrence, MonitoringResult(valuation, report, evidence), self._state.current
        )

    def _record_findings(self, occurrence: OperationOccurrence, report: ConstraintReport) -> None:
        """Write what monitoring measured into the package's own table, and publish it.

        Through the same accept funnel as a valuation's rows, so a run with a store streams
        these to disk as each occurrence passes and a run killed midway keeps every finding it
        made. A run that declared no constraint writes nothing here rather than an empty
        occurrence: there is no finding to record, and a lifecycle entry saying so would be
        noise on every monitoring day.

        `event_time` is the monitoring cutoff -- when the account was judged -- and `offenders`
        is the breaching names joined by a single space, which no instrument id may contain, so
        a reader splits on it without a quoting rule.
        """
        recorder = InvocationRecorder(
            DEFAULT_TABLES,
            run_id=self._frozen_run.identity,
            producer_id=str(self._layer.config.component.component_id),
            stage=occurrence.role.value,
            event_time=occurrence.evaluation_time,
        )
        for finding in report.findings:
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}monitoring",
                {
                    "constraint": finding.constraint_id,
                    "passed": finding.passed,
                    "measured": finding.measured,
                    "bound": finding.bound,
                    "excess": finding.excess,
                    "offenders": " ".join(finding.offenders),
                    "account_version": report.account_version,
                },
            )
        self._state.publish_monitoring(self._state.prepare_monitoring(recorder=recorder))

    def _dispatch_callback(self, occurrence: OperationOccurrence) -> OccurrenceTrace:
        current_ref, before, payload_before = self._guard(
            SimulationStage.CALLBACK_STATE,
            occurrence.evaluation_time,
            self._visible_callback_state,
            family=SimulationFailureFamily.DATA,
            owner=self._layer.config,
        )
        previous_recorder = self._strategy.recorder
        try:
            self._guard(
                SimulationStage.CALLBACK_STATE,
                occurrence.evaluation_time,
                lambda: self._restore_callback_state(before, payload_before),
                family=SimulationFailureFamily.DATA,
                owner=self._layer.config,
            )
            window = self._guard(
                SimulationStage.CALLBACK_WINDOW,
                occurrence.evaluation_time,
                lambda: self._strategy_window(occurrence),
                family=SimulationFailureFamily.DATA,
                owner=self._layer.requirements,
            )
            state_account = self._state.current.account
            if not isinstance(state_account, AccountState):
                self._guard(
                    SimulationStage.CALLBACK_STATE,
                    occurrence.evaluation_time,
                    lambda: self._raise_callback_account_state_error(),
                    family=SimulationFailureFamily.DATA,
                    owner=self._layer.config,
                )
            account = state_account.snapshot
            recorder = self._callback_intent_boundary(
                occurrence,
                self._layer.config,
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
                    owner=self._layer.constraint_requirements,
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
                self._layer.config,
                lambda: self._strategy.decide(
                    StrategyModelContext(
                        occurrence=occurrence,
                        window=window,
                        account=self._callback_account_view(state_account),
                        reads=self._strategy.inputs(),
                        constraint_bounds=constraint_bounds,
                        account_history=self._account_history(),
                    )
                ),
                data_owner=self._layer.requirements,
            )
            # The envelope, stamped here rather than asked of the callback. Every field it
            # adds is one the Flow already had to derive in order to check the author's copy of
            # it, so this replaces a comparison rather than adding a step. Record `125`.
            #
            # The decision is kept beside the intent stamped from it, because a Constraint judges
            # the decision: the five fields stamping adds are facts about the run, and a rule
            # about weights has no business reading any of them.
            if not isinstance(result, (Hold, Rebalance)):
                self._callback_intent_boundary(
                    occurrence,
                    self._layer.config,
                    lambda: _raise_callback_return_type(result),
                )
            if isinstance(result, Rebalance):
                result = self._callback_intent_boundary(
                    occurrence,
                    self._layer.config,
                    lambda: self._stamp_intent(result, occurrence, account, window),
                )

            pending_valuation: PendingValuation | None = None
            if isinstance(result, Hold):
                accepted: Hold | AcceptedIntent = result
                # A Hold still reaches the execution instant, because the book is still
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
                # No constraint check here, deliberately. Construction had the projected bounds
                # and did its best inside them; whether the book actually breached a limit is a
                # question about the committed account, and monitoring asks it (PRD 7.1,
                # architecture 5.7). Judging the decision here also could not see the breach that
                # matters most -- rounding a weight into whole shares moves it, and no fills exist
                # yet.
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
                owner=self._layer.config,
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
                owner=self._layer.config,
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
                    owner=self._layer.requirements,
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
        accepted: Hold | AcceptedIntent,
        pending_valuation: PendingValuation | None = None,
    ) -> object:
        if isinstance(accepted, Hold):
            if pending_valuation is None:
                # Nothing to take: leave whatever the root already had pending untouched.
                return self._state.prepare_callback(
                    memory,
                    payload,
                    lifecycle=lifecycle,
                    recorder=recorder,
                )
            # A Hold still carries a pending identity when an execution instant remains,
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
        # `vqapr.account` carries measurements only, and this path contributes one just in the
        # case where nobody else will: a valuation clock SPARSER than the decision clock leaves
        # sessions its own occurrences never reach, and on those the mark a callback replays is
        # the only record of the book's value there is. 056 measured what dropping it costs --
        # 8 of 10 measurements lost -- so the row survives for exactly that case.
        #
        # What is gone is the row written when a valuation ALREADY recorded this measurement.
        # That one carried `nav=None` and competed with a real value in the same table, which is
        # the null-pairing 056 measured as HML 0.9726 -> 0.6877. A row with nothing to add is now
        # simply not written here; the decision-time facts it also carried moved to their own
        # table below, where no measurement claim competes with them. See `docs/issues/010`.
        mark = self._committed_mark()
        marked_at = getattr(mark, "marked_at", None)
        if (
            mark is not None
            and marked_at is not None
            and marked_at not in self._recorded_measurements
        ):
            prices = {m.instrument_id: m for m in mark.marks.marks}
            observed = mark.observed_at_by_instrument or {}
            recorder.append(
                f"{DEFAULT_TABLE_PREFIX}account",
                {
                    "instrument": _ACCOUNT_IDENTITY,
                    "cash": account.cash,
                    "nav": mark.nav,
                    "quantity": None,
                    "price": None,
                    # When the nav was MEASURED, which is not when this row was written. Dating
                    # the series by the occurrence instead puts every value one commit late;
                    # measured once, that mislabelling took a correlation from 0.93 to 0.02.
                    "observed_at": marked_at,
                    "account_version": account.version,
                },
            )
            positions = sorted(account.positions) if self._record_account_positions else ()
            for instrument in positions:
                valued = prices.get(instrument)
                recorder.append(
                    f"{DEFAULT_TABLE_PREFIX}account",
                    {
                        "instrument": instrument,
                        "cash": None,
                        "nav": None,
                        "quantity": account.positions[instrument],
                        "price": None if valued is None else valued.price,
                        "observed_at": observed.get(instrument),
                        "account_version": account.version,
                    },
                )

        # Nothing else is written here. A `vqapr.decision_account` table briefly stood at this
        # point, holding the cash and positions a callback saw before deciding, on the argument
        # that this is a different fact from what the book was worth.
        #
        # Measured, it was not a different fact. Matched on `account_version`, its rows were
        # IDENTICAL to `vqapr.account`'s on every version the two shared -- the same series offset
        # by one commit, because a callback reports the account it saw and a valuation reports the
        # account it valued. The only genuinely unique row was version 0, the initial account,
        # which `FrozenRun.initial_account_snapshot` already carries. Nothing read it.
        #
        # Removed under this package's own rule: machinery whose only user is its own test is not
        # a feature. If a decision-time account series is ever wanted, it should be designed with
        # the consumer that wants it, which will also say whether it needs to be a table at all.

    def _bind_registry_to_venue(self) -> None:
        """Bind the roster onto the venue itself, so every reader of its rules sees it.

        Handing a bound view to `plan_orders` alone was not enough, and a testbed journey proved
        it: `execute` never receives that view. It reads the venue's OWN rules -- `venue.py` off
        the `rules` property, `krx.py` off the cached `_rules` field -- so `Fill.kind` asked an
        unbound view and every fill in a 599-fill run recorded `None`, with a correctly registered
        roster sitting in the workspace. Registering a roster changed nothing observable, which
        made the whole step unfalsifiable from outside.

        Binding here rather than passing it down because `execute`'s signature is not ours to
        change: `load_exchange` refuses a subclass that overrides `execute`, so the profile's own
        signature is the contract, and a new parameter would break every registered venue.

        Set on the venue rather than on a view it built, because the two profiles hold their rules
        differently: `AcademicExchange.rules` REBUILDS a view on every access, so a view written
        back to it is discarded, while `KrxExchange` serves a cached `_rules` field. Giving both a
        `_registry` to read is the one form that reaches each of them, and it leaves a subclass's
        overridden `rules` property in charge of everything else it adds.

        `object.__setattr__` because `AcademicExchange` is a frozen dataclass.
        """
        if self._registry is None:
            return
        object.__setattr__(self._exchange, "_registry", self._registry)
        cached = getattr(self._exchange, "_rules", None)
        if cached is not None:
            # KRX built its view once at construction; rebind that instance too, since its
            # `rules` property serves the cached object rather than rebuilding.
            object.__setattr__(
                self._exchange, "_rules", cached.with_registry(self._registry)
            )

    def _bound_rules(self) -> object:
        """The rules order planning consumes, with the roster bound if a run has one."""
        rules = self._exchange.rules
        if self._registry is None:
            return rules
        return rules.with_registry(self._registry)

    def _committed_mark(self) -> object | None:
        state = self._state.current.account
        return state.latest_mark if isinstance(state, AccountState) else None

    @staticmethod
    def _callback_account_view(state: AccountState) -> EconomicAccountView:
        """The committed Account as the Strategy sees it: the snapshot, valued at its last mark.

        A callback fires before the occurrence it decides for is executed or valued, so the
        marks it can see are the previous valuation's -- committed, and therefore point-in-time.
        The same builder a monitoring Constraint's view comes from (record `130`), so `nav` and
        `weights()` mean one thing on both sides of a decision. Before the first valuation there
        is no mark, and the view says so with `nav=None` rather than a fabricated zero.
        """
        mark = state.latest_mark
        if mark is not None and mark.marked_at is not None:
            return build_account_view(state.snapshot, mark.marks, mark.marked_at)
        snapshot = state.snapshot
        return EconomicAccountView(
            cash=snapshot.cash,
            positions=dict(snapshot.positions),
            nav=None,
            nav_observed_at=None,
        )

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
            producer_id=str(self._layer.config.component.component_id),
            stage=occurrence.role.value,
            event_time=occurrence.evaluation_time,
        )

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
        accepted: Hold | AcceptedIntent,
        projected: tuple[object, ...],
    ) -> tuple[CallbackEvidence, LifecycleTrace]:
        evidence = CallbackEvidence(
            run_identity=self._frozen_run.identity,
            strategy=self._layer.config,
            agenda=self._layer.agenda,
            occurrence=occurrence,
            cutoff=occurrence.evaluation_time,
            root_version=self._state.current.version,
            account=account,
            current_model_state_ref=current_ref,
            committed_model_state_ref=committed_ref,
            strategy_accesses=window.accesses,
            actual_source_refs=self._callback_actual_source_refs(occurrence, window),
            decision=accepted,
            pending=None if isinstance(accepted, Hold) else accepted,
            # The projections only. What a callback's evidence carries about constraints is
            # what the rules permitted at that instant, not a verdict on the decision -- there is
            # no verdict at this point, by design (PRD 7.1). The verdict is monitoring's.
            constraints=projected,
        )
        lifecycle = LifecycleTrace(
            LifecycleKind.NO_DECISION
            if isinstance(accepted, Hold)
            else LifecycleKind.ACCEPTED_INTENT,
            evidence,
        )
        return evidence, lifecycle

    def _callback_actual_source_refs(
        self, occurrence: OperationOccurrence, window: ModelWindow
    ) -> tuple[IntentSourceRef, ...]:
        return self._guard(
            SimulationStage.CALLBACK_WINDOW,
            occurrence.evaluation_time,
            lambda: self._actual_source_refs(window),
            family=SimulationFailureFamily.DATA,
            owner=self._layer.requirements,
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

    def _stamp_intent(
        self,
        decision: Rebalance,
        occurrence: OperationOccurrence,
        account: AccountSnapshot,
        window: ModelWindow,
    ) -> EconomicPortfolioIntent:
        """Turn one economic decision into the intent the Flow accepts.

        Five of an intent's eight fields are facts about the RUN, not about the decision: which
        Strategy this is, what it read, which account version it saw, which model state was
        visible, and the intent's own identity. The callback cannot know four of them correctly
        and can only copy the fifth, so asking for them made every author restate what the Flow
        already knew -- and made a wrong restatement a possible outcome.

        The id is `uuid5` over `(strategy_id, occurrence_id)` rather than random, so the same
        decision in the same occurrence of the same run mints the same identity. A replayed run
        produces byte-identical intents, which is what makes a record comparable to itself.
        """
        strategy_id = str(self._layer.config.component.component_id)
        targets = tuple(
            PortfolioTarget(instrument, weight=weight)
            for instrument, weight in sorted(decision.target_weights.items())
        )
        return EconomicPortfolioIntent(
            uuid5(NAMESPACE_URL, f"{strategy_id}/{occurrence.occurrence_id}"),
            strategy_id,
            targets,
            Decimal(decision.cash_weight),
            decision.budget,
            self._actual_source_refs(window),
            account.version,
            self._state.current.current_model_state_ref,
        )

    def _validate_intent_authority(
        self,
        intent: EconomicPortfolioIntent,
        account: AccountSnapshot,
        window: ModelWindow,
    ) -> None:
        """The one thing left to check: that the author named instruments this run trades.

        The four comparisons that stood here -- strategy id, model state ref, account version
        seen, source refs -- each read a field the callback supplied and compared it against a
        value this class derived. Record `125` stamps those fields from the derived values
        instead, so there is nothing left to disagree with. What survives is a real check on a
        real authored value: `target_weights` is the author's, and a name outside the frozen
        universe is an authoring error the Flow must refuse rather than execute.
        """
        outside_universe = tuple(
            target.instrument_id
            for target in intent.targets
            if target.instrument_id not in self._frozen_run.instrument_set
        )
        if outside_universe:
            raise ValueError(
                f"intent targets are outside the frozen instrument universe: {outside_universe}"
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
                # The run owns a scan session; the horizon is the one query that reads every
                # distinct instant in the execution table, so it is the last one that should be
                # opening a connection of its own.
                session=self._scan_session,
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
          callbacks never values against venue prices, so a Hold in it stays what it was.
        - **No execution instant remains in the horizon.** There is nothing left to value
          against, and a run ending on a Hold must still finalize.
        """
        if self._state.current.pending_accepted_intent is not None:
            return None
        frozen = self._frozen_run
        execution_input = frozen.execution_input
        if execution_input is None or frozen.end is None or frozen.start is None:
            # A run declared without execution authority never values against venue prices. That
            # is a legitimate configuration -- a research run that only exercises callbacks -- and
            # a Hold in it stays exactly what it was.
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
            valuation_id=self._pending_valuation_key(
                self._frozen_run.identity, occurrence.role.value, occurrence.evaluation_time
            ),
        )

    @staticmethod
    def _pending_valuation_key(identity: object, role: str, instant: datetime) -> UUID:
        """The pending identity for a valuation, discriminated by role as well as instant.

        The role belongs in the key. Without it, occurrences differing only in role mint the SAME
        uuid5 at one instant in one run, and `pending_id` is the token that proves a completion
        matches its own preparation (`run_state.py:346-348`, `:434-436`). Two identical ids would
        degrade that invariant from a proof to a coincidence.
        """
        return uuid5(_VALUATION_NAMESPACE, f"{identity}|{role}|{instant.isoformat()}")

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
