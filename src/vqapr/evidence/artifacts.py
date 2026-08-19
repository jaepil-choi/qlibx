"""Canonical, immutable lineage emitted by the simulation Flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.errors import VqaprError
from vqapr.domain.references import ModelStateRef
from vqapr.domain.timestamps import require_tz_aware

MAX_OBSERVED_CHARS = 500
"""Upper bound for one serialized observation. The unbounded body belongs in a dump file."""


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
    ) -> None:
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
        super().__init__(f"{stage.value}: {cause}")

    def as_dict(self) -> dict[str, object]:
        """The agent-readable form; ``str(err)`` remains the human one.

        Top-level keys match ``VqaprError.as_dict()`` so a caller can serialize either failure
        through one path instead of branching on the exception type. Only bounded scalars are
        included: the replay coordinates collect into ``at``, while unbounded owner objects and
        the traceback stay out and belong in a dump file.
        """
        cause = self.cause
        if isinstance(cause, VqaprError):
            failures = cause.as_dict()["failures"]
        else:
            observed = str(cause)
            if len(observed) > MAX_OBSERVED_CHARS:
                observed = observed[:MAX_OBSERVED_CHARS] + "..."
            failures = [
                {
                    "code": f"{self.stage.value}.{type(cause).__name__}",
                    "requirement": "the guarded boundary must complete without raising",
                    "observed": observed,
                    "examples": [],
                    "example_total": 0,
                }
            ]
        retry = self.retry_precondition
        return {
            "stage": str(self.stage),
            "family": str(self.family),
            "kind": str(self.kind),
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
    valuation_config: object
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
    valuation_config: object
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
    valuation_agenda: object
    monitoring_agenda: object | None
    cutoff: datetime
    account: AccountSnapshot | None
    root_version: int
    mutation: bool = False
