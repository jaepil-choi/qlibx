"""Canonical, immutable lineage emitted by the simulation Flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.errors import Failure, FailureSource, VqaprError, status_of
from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.values import MarkSummary, require_tz_aware

MAX_OBSERVED_CHARS = 500
"""Upper bound for one serialized observation. The unbounded body belongs in a dump file."""


_CALLBACK_STAGES: Final = frozenset(
    {
        "simulation.callback.state",
        "simulation.callback.window",
        "simulation.callback.intent",
        "simulation.callback.publication",
    }
)
"""The four stages whose code is the author's own, so their advice points at the author's file.

Held as strings rather than `SimulationStage` members because `SimulationStage` is declared below,
and a set of members would have to be built after the class rather than beside the two helpers that
read it.
"""


def _requirement_for(stage: StrEnum) -> str:
    """What was required of the code that raised, in terms of what its author controls.

    "The guarded boundary must complete without raising" -- the sentence this replaces for callback
    stages -- is a statement about this package's own plumbing. A reader who has just been handed a
    `ValueError` from their own `decide()` learns nothing from it about what they did.
    """
    if str(stage) in _CALLBACK_STAGES:
        return "the strategy callback must return without raising"
    return "the guarded boundary must complete without raising"


def _fix_for(stage: StrEnum, cause: BaseException) -> str:
    """The sentence the skill tells a reader to read FIRST, and which used to be absent entirely.

    A raised exception carries no repair advice of its own, so the best available instruction is
    where to look: the author's callback for a callback stage, and the run's own record otherwise.
    Naming the exception type keeps it concrete without pretending to know the specific cause.
    """
    kind = type(cause).__name__
    if str(stage) in _CALLBACK_STAGES:
        return (
            f"your callback raised {kind}; read `observed` for the message it carried, fix the "
            "component, and re-run -- registration replaces in place, so no new id is needed"
        )
    return (
        f"the framework raised {kind} at {stage}; read `observed`, and if the message names "
        "something you declared, correct it and re-run"
    )


class SimulationFailureKind(StrEnum):
    """Closed mutation taxonomy; retry behaviour is determined from this value."""

    PRE_COMMIT = "PRE_COMMIT"
    FAILED_AFTER_COMMIT = "FAILED_AFTER_COMMIT"


class SimulationStage(StrEnum):
    START = "simulation.start"
    CALLBACK_STATE = "simulation.callback.state"
    CALLBACK_WINDOW = "simulation.callback.window"
    CALLBACK_INTENT = "simulation.callback.intent"
    CALLBACK_PUBLICATION = "simulation.callback.publication"
    MARKET_ACCRUE = "simulation.market.accrue"
    DUE_SNAPSHOT = "simulation.due.snapshot"
    DUE_INSTRUMENT_DECLARATION = "simulation.due.instrument_declaration"
    DUE_ORDER_PLANNING = "simulation.due.order_planning"
    DUE_EXCHANGE_EXECUTION = "simulation.due.exchange_execution"
    DUE_ACCOUNT_PREPARATION = "simulation.due.account_preparation"
    DUE_ACCOUNT_COMMIT = "simulation.due.account_commit"
    DUE_VALUATION_SELECTION = "simulation.due.valuation_selection"
    DUE_VALUATION_MARK = "simulation.due.valuation_mark"
    DUE_ACCOUNT_MARK = "simulation.due.account_mark"
    DUE_FEEDBACK_CANDIDATE = "simulation.due.feedback_candidate"
    DUE_FEEDBACK_PUBLICATION = "simulation.due.feedback_publication"
    MARKET_COMPLIANCE = "simulation.market.compliance"
    FINALIZE = "simulation.finalize"


_PRE_COMMIT: Final = SimulationFailureKind.PRE_COMMIT


def _code_for(stage: SimulationStage) -> str:
    """`strategy.<stage>`: the code of a bare raise inside a strategy's flow.

    `strategy.callback.intent`, `strategy.due.account_commit`, ... -- the subject is the strategy
    whose flow raised, and the detail is the `SimulationStage` without its `simulation.` prefix.
    Who must act rides on `status` (502 when the innermost frame is the author's, 500 when it is
    the framework's), not on the code (record `171`).
    """
    return f"strategy.{stage.value.removeprefix('simulation.')}"


@dataclass(frozen=True, slots=True)
class FailureObservation:
    """Exact exception type and immutable arguments observed at the boundary."""

    exception_type: type[Exception]
    arguments: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class RetryPrecondition:
    """Typed retry boundary rather than an advisory string."""

    requires_replay_from_root: bool
    required_pending_id: str | None


class SimulationFailure(RuntimeError, ValueError):
    """Typed failure containing the complete visible replay boundary."""

    def __init__(
        self,
        *,
        stage: SimulationStage,
        clock: datetime,
        failed_requirement: object | None,
        observed: object,
        cause: Exception,
        retry_precondition: object,
        correlation_id: str,
        frozen_run_identity: str,
        cutoff: datetime,
        root_version: int,
        model_version: int,
        model_state_ref: ModelStateRef | None,
        account_version: int | None,
        pending_id: str | None,
        kind: SimulationFailureKind = _PRE_COMMIT,
        component_id: str | None = None,
        source: FailureSource | None = None,
    ) -> None:
        """`component_id` names the strategy whose flow raised, and `source` where in the
        author's own file it was raised from, when a frame of that file is on the traceback.
        Both were absent (`docs/issues/archive/071`): an eight-strategy run refused with a message
        that named no strategy, and `source` was three nulls on every callback failure."""
        require_tz_aware(clock, name="clock")
        require_tz_aware(cutoff, name="cutoff")
        if kind is _PRE_COMMIT and pending_id is None and stage.name.startswith("DUE_"):
            # A due operation always has an accepted pending identity before its commit.
            raise ValueError("pre-commit due failures must retain their pending identity")
        self.kind = kind
        self.stage = stage
        self.clock = clock
        self.mutation = kind is SimulationFailureKind.FAILED_AFTER_COMMIT
        self.failed_requirement = failed_requirement
        self.observed = observed
        self.cause = cause
        self.retry_precondition = retry_precondition
        self.correlation_id = correlation_id
        self.frozen_run_identity = frozen_run_identity
        self.cutoff = cutoff
        self.root_version = root_version
        self.model_version = model_version
        self.model_state_ref = model_state_ref
        self.account_version = account_version
        self.pending_id = pending_id
        self.component_id = None if component_id is None else str(component_id)
        self.source = source if source is not None else FailureSource()
        super().__init__(
            f"{stage.value}: {cause}"
            if component_id is None
            else f"{stage.value} [{component_id}]: {cause}"
        )

    def as_dict(self) -> dict[str, object]:
        """The agent-readable form; ``str(err)`` remains the human one.

        Top-level keys match ``VqaprError.as_dict()`` so a caller can serialize either failure
        through one path instead of branching on the exception type, and each failure entry IS
        ``Failure.as_dict()``: a bare raise is given a ``Failure`` here and rendered by the one
        implementation rather than by a second literal of the same keys. The exception rides
        whole in that entry's ``cause`` -- type, message, the full traceback -- with a status by
        whose frame raised it (record `171`); unbounded owner objects stay out, and the replay
        coordinates collect into ``at``.
        """
        cause = self.cause
        if isinstance(cause, VqaprError):
            failures = cause.as_dict()["failures"]
        else:
            observed = str(cause)
            if len(observed) > MAX_OBSERVED_CHARS:
                observed = observed[:MAX_OBSERVED_CHARS] + "..."
            failures = [
                Failure.bounded(
                    _code_for(self.stage),
                    _requirement_for(self.stage),
                    status=status_of(cause),
                    observed=observed,
                    fix=_fix_for(self.stage, cause),
                    cause=cause,
                    source=self.source,
                ).as_dict()
            ]
        retry = self.retry_precondition
        return {
            "stage": str(self.stage),
            "kind": str(self.kind),
            # Which strategy of the run this is about. A run holds several (record `139`), and
            # the envelope carried a clock and an account version but no name.
            "component_id": self.component_id,
            "mutation": self.mutation,
            "retry_precondition": (
                {
                    "requires_replay_from_root": retry.requires_replay_from_root,
                    "required_pending_id": retry.required_pending_id,
                }
                if isinstance(retry, RetryPrecondition)
                else None
            ),
            "correlation_id": self.correlation_id,
            "failures": failures,
            "at": {
                "frozen_run_identity": self.frozen_run_identity,
                "clock": self.clock.isoformat(),
                "cutoff": self.cutoff.isoformat(),
                "root_version": self.root_version,
                "model_version": self.model_version,
                "account_version": self.account_version,
                "pending_id": self.pending_id,
            },
        }


@dataclass(frozen=True, slots=True)
class CallbackEvidence:
    """Pre-publication callback authority, inputs, decision, and candidate output."""

    run_identity: str
    strategy: object
    agenda: object
    occurrence: object
    cutoff: datetime
    root_version: int
    account: AccountSnapshot
    current_model_state_ref: ModelStateRef
    committed_model_state_ref: ModelStateRef
    strategy_accesses: tuple[object, ...]
    actual_source_refs: tuple[object, ...]
    decision: object
    pending: object | None
    mutation: bool = False

    def __post_init__(self) -> None:
        if self.mutation:
            raise ValueError("callback evidence must precede publication")
        require_tz_aware(self.cutoff, name="cutoff")


@dataclass(frozen=True, slots=True)
class AccountCommitEvidence:
    """All exact inputs and committed values for the irreversible Account fill."""

    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    pending: object
    target: object
    fill_convention: object
    execution_snapshot: object
    """The snapshot's partitions and row count (`ExecutionSnapshotSummary`, record `224`), not its
    rows: a 3,000-name book's rows per fill are the venue's data, read again from the table."""
    planning_nav: object
    planning_cash_target: object
    planning_budget: object
    intended_targets: tuple[object, ...]
    requested_orders: object
    dealt_fills: object
    before: AccountSnapshot
    committed: AccountSnapshot
    root_version: int
    account_version_before: int
    account_version_committed: int
    mutation: bool = True


@dataclass(frozen=True, slots=True)
class MarkEvidence:
    """Valuation declaration, the marks' summary, and post-mark Account authority.

    `selected` is how many names the venue's snapshot priced and `marks` the batch's total and
    count (record `224`): the marks themselves are `vqapr.account` rows by the time this exists,
    and keeping a `SelectedMark` and a `Mark` per name per fill held instants x names objects
    until the run ended.
    """

    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    selected: int
    marks: MarkSummary
    limitations: tuple[object, ...]
    account: AccountSnapshot
    root_version: int
    account_version: int
    mutation: bool = True


@dataclass(frozen=True, slots=True)
class FeedbackEvidence:
    """Published feedback transition; no fallible work follows Account commit."""

    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    pending: object
    candidates: tuple[object, ...]
    root_version: int
    account_version: int
    mutation: bool = True


@dataclass(frozen=True, slots=True)
class DueExecutionEvidence:
    """Complete due lifecycle lineage, including commit, marking, and feedback."""

    commit: AccountCommitEvidence
    mark: MarkEvidence
    feedback: FeedbackEvidence


@dataclass(frozen=True, slots=True)
class ValuationEvidence:
    """A held book valued at a market-clock instant: the account it valued and the marks'
    summary (record `224`; the marks are `vqapr.account` rows)."""

    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    account: AccountSnapshot
    marks: MarkSummary
    root_version: int
    account_version: int
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class MonitoringEvidence:
    """What the declared Compliance rules found on the committed, marked book at one market-clock
    instant (design §7.2). No occurrence: the observer has no decision of its own to point at."""

    run_identity: str
    agenda: object
    cutoff: datetime
    account: AccountSnapshot
    valuation: ValuationEvidence
    report: object
    root_version: int
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class FinalizationEvidence:
    run_identity: str
    strategy_agenda: object
    cutoff: datetime
    account: AccountSnapshot | None
    root_version: int
    mutation: bool = False
