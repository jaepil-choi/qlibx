"""The value classes of a simulation, and the state its four phases share.

Record `147` (deletion campaign Step 6) split `SimulationFlow` -- 2,200 lines, 55 methods -- into
the loop (`simulation.py`), the callback phase (`callback.py`: decide -> intent), the execution
phase (`execution.py`: intent -> fill -> commit) and the valuation phase (`valuation.py`: mark ->
account, and monitoring). The phases share this module: the dataclasses every phase produces or
consumes, the package tables, and `FlowContext`, the one object holding the run's state and the
failure envelope (`guard`, `failure`, `due_boundary`).
"""

from __future__ import annotations

import inspect
import time
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from vqapr.account.account import Account
from vqapr.account.snapshot import AccountSnapshot
from vqapr.authoring import AccountHistoryInput, Constraint, StrategyModel
from vqapr.constraints.evaluation import ConstraintReport
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    VqaprError,
)
from vqapr.domain.values import MarkBatch
from vqapr.evidence.artifacts import (
    CallbackEvidence,
    FailureObservation,
    MonitoringEvidence,
    RetryPrecondition,
    SimulationFailure,
    SimulationFailureFamily,
    SimulationFailureKind,
    SimulationStage,
    ValuationEvidence,
)
from vqapr.evidence.tables import TableSpec
from vqapr.exchange.conventions import ExactExecutionTarget, ExecutionHorizon
from vqapr.exchange.venue import Exchange
from vqapr.flow.frozen import FrozenRun, FrozenStrategy
from vqapr.flow.loop import DueExecutionEnvelope
from vqapr.flow.marking import ValuationService
from vqapr.flow.run_state import (
    FILL_TABLE,
    AcceptedRunState,
    RunStateRepository,
)
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
)


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
    timing: Mapping[str, float] = field(default_factory=dict)
    """Seconds spent, by phase, over the whole run (`docs/issues/068`): `total`, `callback`
    (window and decide, every static occurrence), `due` (every fill-side item), and one entry
    per due stage -- `simulation.due.snapshot`, `simulation.due.order_planning`, ... -- so a
    reader learns where a run's wall clock went without a profiler. Wall-clock, not CPU."""


def callback_evidence(result: SimulationResult) -> tuple[CallbackEvidence, ...]:
    """Every Strategy callback evidence a finished run published, in lifecycle order.

    A run's decisions are reachable only through its state root, and reconstructing them from
    ``occurrences`` would mean re-deriving what the Flow already stamped. Read by tests and
    showcases that want the decisions in-process; a later run that wants them reads the run's
    recorded ``vqapr.weight`` table, registered as a dataset (one-shape campaign Step 4).
    Declining callbacks are included, because whether a decline counts is the reader's rule to
    apply, not this accessor's.
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
    """Evidence returned only after the complete post-decision account chain.

    `monitoring` is what the declared constraints found on the committed, marked book right
    after this commit (record `148`), or `None` when the run declared none.
    """

    consumed_pending_id: str
    account_version: int
    post_account_result: object
    monitoring: object | None = None

    @property
    def report(self) -> object | None:
        """The constraint report, where `contract_report` looks for one."""
        return None if self.monitoring is None else self.monitoring.report

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
class HeldResult:
    """A held book valued at its execution instant, and what monitoring found there."""

    valuation: object
    monitoring: object | None = None

    @property
    def report(self) -> object | None:
        return None if self.monitoring is None else self.monitoring.report


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
        (
            "constraint",
            "passed",
            "measured",
            "bound",
            "excess",
            "verdict",
            "tolerance",
            "offenders",
            "account_version",
        ),
    ),
    TableSpec(
        FILL_TABLE,
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

FRAMEWORK_TABLES = tuple(spec.table_id for spec in DEFAULT_TABLES)
"""The tables the package records on a strategy's behalf, which nobody declares -- derived from
`DEFAULT_TABLES` rather than listed again (`flow/reporting.py` listed them a second time; one-shape
Step 6 folded it here). `vqapr.monitoring` is written only by a strategy that declared a
constraint, but it is the package's table either way."""
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


def _component_id_of(layer: object) -> str:
    """The component id of a strategy layer (`config.component`) or a datamodel layer
    (`component`); the failure envelope names the member either way."""
    config = getattr(layer, "config", None)
    ref = getattr(config, "component", None) if config is not None else None
    if ref is None:
        ref = getattr(layer, "component", None)
    return str(getattr(ref, "component_id", "?"))


def _author_frame(cause: BaseException, strategy: object, component_id: str) -> FailureSource:
    """Where in the author's own file the failure came from, as a `FailureSource`.

    The traceback of a callback failure runs from the Flow's guard down through the author's
    `decide()` and, often, back into this package -- a `Rebalance` refused in its validator is
    raised in `authoring.py` from a line in the author's file. The frame the author needs is the
    innermost one IN THEIR FILE, so every frame is compared against the file the strategy class
    was loaded from and the last match wins. `key_path` names the strategy either way, so a
    framework raise with no author frame still says which strategy it was about
    (`docs/issues/071`).
    """
    source = FailureSource(key_path=f"strategies.{component_id}")
    try:
        loaded_from = inspect.getsourcefile(type(strategy)) or inspect.getfile(type(strategy))
    except (TypeError, OSError):
        return source
    wanted = _resolved(loaded_from)
    found: tuple[str, int] | None = None
    trace = cause.__traceback__
    while trace is not None:
        filename = trace.tb_frame.f_code.co_filename
        if filename == loaded_from or _resolved(filename) == wanted:
            found = (filename, trace.tb_lineno)
        trace = trace.tb_next
    if found is None:
        return source
    return FailureSource(file=found[0], key_path=source.key_path, line=found[1])


def _resolved(filename: str) -> Path:
    """The path with symlinks and relative segments settled, or as given when that fails."""
    try:
        return Path(filename).resolve()
    except OSError:
        return Path(filename)


@dataclass(kw_only=True, slots=True)
class FlowContext:
    """What every phase of one strategy's run shares: the frozen run, this strategy's layer, the run
    state, the account and venue, and the failure envelope. Built by `SimulationFlow`, read by
    `CallbackPhase`, `ExecutionPhase` and `ValuationPhase`; nothing here dispatches."""

    frozen_run: FrozenRun
    layer: FrozenStrategy
    state: RunStateRepository
    account: Account
    exchange: Exchange
    strategy: StrategyModel
    constraints: tuple[Constraint, ...]
    valuation_service: ValuationService
    strategy_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow]
    constraint_window_for_occurrence: Callable[[OperationOccurrence], ModelWindow]
    constraint_window_at: Callable[[datetime], ModelWindow]
    scan_session: object | None = None
    registry: object | None = None
    reference_price: str | None = None
    record_account_positions: bool = True
    account_history_declaration: AccountHistoryInput | None = None
    # Mutable bookkeeping is local to this strategy; authorities above are supplied once.
    recorded_measurements: set[object] = field(default_factory=set)
    horizon: ExecutionHorizon | None = None
    timing: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def timed(self, phase: str) -> Iterator[None]:
        """Measure a lexical phase without adding frames to the operation it contains."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.timing[phase] = self.timing.get(phase, 0.0) + (time.perf_counter() - started)

    def in_agenda_zone(self, instant: datetime) -> datetime:
        """An instant expressed in the strategy agenda's zone; the same instant.

        Every package table stamps `event_time` in that zone (`docs/issues/058`): the execution
        table normalises targets to UTC, and a reader lining a fill up against the NAV or the
        monitoring row that followed it was converting by hand.
        """
        zone = self.layer.agenda.timezone
        return instant.astimezone(ZoneInfo(zone)) if zone else instant

    @contextmanager
    def guard(
        self,
        stage: SimulationStage,
        cutoff: datetime,
        *,
        family: SimulationFailureFamily,
        owner: object,
    ) -> Iterator[None]:
        try:
            yield
        except SimulationFailure:
            raise
        except Exception as error:
            raise self.failure(
                stage=stage,
                cutoff=cutoff,
                owner=owner,
                family=family,
                cause=error,
                kind=SimulationFailureKind.PRE_COMMIT,
            ) from error

    def failure(
        self,
        *,
        stage: SimulationStage,
        cutoff: datetime,
        owner: object,
        family: SimulationFailureFamily,
        cause: Exception,
        kind: SimulationFailureKind,
    ) -> SimulationFailure:
        root = self.state.current
        account = root.account
        pending = root.pending_accepted_intent
        component_id = _component_id_of(self.layer)
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
            correlation_id=self.frozen_run.identity,
            frozen_run_identity=self.frozen_run.identity,
            cutoff=cutoff,
            root_version=root.version,
            model_version=root.model_state_commit_count,
            model_state_ref=root.current_model_state_ref,
            account_version=None if account is None else account.snapshot.version,
            pending_id=getattr(pending, "pending_id", None),
            cause=cause,
            kind=kind,
            component_id=component_id,
            source=_author_frame(cause, self.strategy, component_id),
        )

    @contextmanager
    def due_boundary(
        self,
        *,
        stage: SimulationStage,
        cutoff: datetime,
        owner: object,
        family: SimulationFailureFamily,
        kind: SimulationFailureKind,
    ) -> Iterator[None]:
        try:
            # The due stages run one after another inside one due item, never nested, so their
            # seconds add up to the due item's and each is reported under its own name.
            with self.timed(stage.value):
                yield
        except SimulationFailure:
            raise
        except Exception as error:
            raise self.failure(
                stage=stage,
                cutoff=cutoff,
                owner=owner,
                family=family,
                cause=error,
                kind=kind,
            ) from error
