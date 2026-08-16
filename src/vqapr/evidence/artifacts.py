"""Canonical, immutable lineage emitted by the simulation Flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.references import ModelStateRef
from vqapr.domain.timestamps import require_tz_aware


class SimulationFailureFamily(StrEnum):
    """Closed ownership family for a failed simulation operation."""

    SIMULATION = "SIMULATION"


class SimulationFailureKind(StrEnum):
    """Closed mutation taxonomy; retry behaviour is determined from this value."""

    PRE_COMMIT = "PRE_COMMIT"
    FAILED_AFTER_COMMIT = "FAILED_AFTER_COMMIT"


class SimulationStage(StrEnum):
    START = "simulation.start"
    CALLBACK = "simulation.callback"
    DUE = "simulation.due"
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
        if not isinstance(stage, SimulationStage):
            raise TypeError("stage must be a SimulationStage")
        require_tz_aware(clock, name="clock")
        require_tz_aware(cutoff, name="cutoff")
        if not isinstance(cause, Exception):
            raise TypeError("cause must be an Exception")
        if not isinstance(kind, SimulationFailureKind):
            raise TypeError("kind must be a SimulationFailureKind")
        if kind is _PRE_COMMIT and pending_id is None and stage is SimulationStage.DUE:
            # A due operation always has an accepted pending identity before its commit.
            raise ValueError("pre-commit due failures must retain their pending identity")
        self.family = SimulationFailureFamily.SIMULATION
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
    mutation: bool = False


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
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class FeedbackEvidence:
    """Prepared feedback publication; no work remains after Account commit."""

    run_identity: str
    agenda: object
    occurrence: object
    cutoff: datetime
    pending: object
    candidates: tuple[object, ...]
    root_version: int
    account_version: int
    mutation: bool = False


@dataclass(frozen=True, slots=True)
class DueExecutionEvidence:
    """Complete due lifecycle lineage, including commit, marking, and feedback."""

    commit: AccountCommitEvidence
    mark: MarkEvidence
    feedback: FeedbackEvidence


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
