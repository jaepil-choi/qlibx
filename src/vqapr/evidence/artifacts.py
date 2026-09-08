"""Canonical, immutable lineage emitted by the simulation Flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.errors import ExplainTopic, Failure, FailureSource, VqaprError
from vqapr.domain.identifiers import ModelStateRef
from vqapr.domain.values import require_tz_aware

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


class SimulationFailureFamily(StrEnum):
    """Closed ownership family for a failed simulation operation."""

    DATA = "DATA"
    INTENT = "INTENT"
    ORDER = "ORDER"
    EXCHANGE = "EXCHANGE"
    ACCOUNT = "ACCOUNT"
    VALUATION = "VALUATION"
    PUBLICATION = "PUBLICATION"
    FINALIZATION = "FINALIZATION"


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
    DUE_SNAPSHOT = "simulation.due.snapshot"
    DUE_ORDER_PLANNING = "simulation.due.order_planning"
    DUE_EXCHANGE_EXECUTION = "simulation.due.exchange_execution"
    DUE_ACCOUNT_PREPARATION = "simulation.due.account_preparation"
    DUE_ACCOUNT_COMMIT = "simulation.due.account_commit"
    DUE_VALUATION_SELECTION = "simulation.due.valuation_selection"
    DUE_VALUATION_MARK = "simulation.due.valuation_mark"
    DUE_ACCOUNT_MARK = "simulation.due.account_mark"
    DUE_FEEDBACK_CANDIDATE = "simulation.due.feedback_candidate"
    DUE_FEEDBACK_PUBLICATION = "simulation.due.feedback_publication"
    VALUATION = "simulation.valuation"
    MONITORING = "simulation.monitoring"
    FINALIZE = "simulation.finalize"


_PRE_COMMIT: Final = SimulationFailureKind.PRE_COMMIT

_EXPLAIN_BY_STAGE: Final[dict[SimulationStage, ExplainTopic]] = {
    SimulationStage.CALLBACK_STATE: ExplainTopic.COMPONENT_CONTRACT,
    SimulationStage.CALLBACK_WINDOW: ExplainTopic.COMPONENT_CONTRACT,
    SimulationStage.CALLBACK_INTENT: ExplainTopic.COMPONENT_CONTRACT,
    SimulationStage.CALLBACK_PUBLICATION: ExplainTopic.PUBLICATION,
}
"""Which recovery section answers a raise at each stage.

Only existing topics are used. Every one of these already resolves to a `### Recovering from:`
section in `SKILL.md`, and `tests/characterization/test_explain_topics.py` pins that correspondence
in both directions -- so adding a topic here without writing its section, or writing a section with
no topic, fails the suite. Stages absent from this map fall back to `run-precondition`, which is
the topic for "a precondition of the run did not hold".
"""


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
        family: SimulationFailureFamily,
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
        Both were absent (`docs/issues/071`): an eight-strategy run refused with a message
        that named no strategy, and `source` was three nulls on every callback failure."""
        if not isinstance(family, SimulationFailureFamily):
            raise TypeError("family must be a SimulationFailureFamily")
        if not isinstance(stage, SimulationStage):
            raise TypeError("stage must be a SimulationStage")
        require_tz_aware(clock, name="clock")
        require_tz_aware(cutoff, name="cutoff")
        if not isinstance(cause, Exception):
            raise TypeError("cause must be an Exception")
        if not isinstance(kind, SimulationFailureKind):
            raise TypeError("kind must be a SimulationFailureKind")
        if kind is _PRE_COMMIT and pending_id is None and stage.name.startswith("DUE_"):
            # A due operation always has an accepted pending identity before its commit.
            raise ValueError("pre-commit due failures must retain their pending identity")
        self.family = family
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
        implementation rather than by a second literal of the same eight keys. Only bounded
        scalars are included: the replay coordinates collect into ``at``, while unbounded owner
        objects and the traceback stay out and belong in a dump file.
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
                    f"{self.stage.value}.{type(cause).__name__}",
                    _requirement_for(self.stage),
                    observed=observed,
                    fix=_fix_for(self.stage, cause),
                    explain=_EXPLAIN_BY_STAGE.get(self.stage, ExplainTopic.RUN_PRECONDITION),
                    source=self.source,
                ).as_dict()
            ]
        retry = self.retry_precondition
        return {
            "stage": str(self.stage),
            "family": str(self.family),
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
    constraints: tuple[object, ...]
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
    """Valuation declaration, selected marks, and post-mark Account authority."""

    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    selected_marks: object
    marks: object
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

    def __post_init__(self) -> None:
        if not isinstance(self.commit, AccountCommitEvidence):
            raise TypeError("commit must be an AccountCommitEvidence")
        if not isinstance(self.mark, MarkEvidence):
            raise TypeError("mark must be a MarkEvidence")
        if not isinstance(self.feedback, FeedbackEvidence):
            raise TypeError("feedback must be a FeedbackEvidence")


@dataclass(frozen=True, slots=True)
class ValuationEvidence:
    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    account: AccountSnapshot
    marks: object
    root_version: int
    account_version: int
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class MonitoringEvidence:
    run_identity: str
    agenda: object
    occurrence: object
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
