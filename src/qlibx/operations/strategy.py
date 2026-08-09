"""Direct Strategy contracts."""

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, model_validator

from qlibx.context import (
    AccessRecord,
    FeedbackAccessRecord,
    MemoryAccessRecord,
    SessionPerformanceAccessRecord,
    StateAccessRecord,
    StrategyView,
)
from qlibx.data import ComponentRequirement
from qlibx.domain import BudgetMode
from qlibx.models import QlibxModel
from qlibx.operations.artifacts import StrategyArtifactBinding, StrategyArtifactRequirement


class DecisionAction(StrEnum):
    TARGET = "target"
    HOLD = "hold"
    RESEARCH_ONLY = "research_only"


class WeightEntry(QlibxModel):
    instrument: str = Field(min_length=1)
    weight: float

    @model_validator(mode="after")
    def validate_finite(self) -> "WeightEntry":
        if not math.isfinite(self.weight):
            raise ValueError("weight must be finite")
        return self


class StrategyDraft(QlibxModel):
    weights: tuple[WeightEntry, ...]
    budget_mode: BudgetMode
    target_gross: float = Field(gt=0)
    decision_action: DecisionAction = DecisionAction.TARGET
    diagnostics: tuple[str, ...] = ()
    path_dependent: bool = False
    state_identity: str | None = None
    feedback_cursor: str | None = None
    proposed_memory: dict[str, object] | None = None
    expected_memory_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_budget(self) -> "StrategyDraft":
        instruments = [entry.instrument for entry in self.weights]
        if len(instruments) != len(set(instruments)):
            raise ValueError("strategy weights must have unique instruments")
        gross = sum(abs(entry.weight) for entry in self.weights)
        tolerance = 1e-10
        if gross > self.target_gross + tolerance:
            raise ValueError("strategy gross exceeds declared target")
        if self.budget_mode is BudgetMode.FIXED and abs(gross - self.target_gross) > tolerance:
            raise ValueError("fixed-budget strategy must meet its declared gross target")
        if self.path_dependent and not self.state_identity:
            raise ValueError("path-dependent strategy requires state_identity")
        if self.decision_action is DecisionAction.HOLD and self.weights:
            raise ValueError("an explicit hold must not contain target weights")
        if (self.proposed_memory is None) != (self.expected_memory_version is None):
            raise ValueError(
                "proposed_memory and expected_memory_version must be provided together"
            )
        return self


class _StrategyResultFields(QlibxModel):
    invocation_id: str
    strategy_id: str
    evaluation_time: datetime
    weights: tuple[WeightEntry, ...]
    budget_mode: BudgetMode
    target_gross: float
    invested_gross: float
    net_exposure: float
    residual_budget: float
    decision_action: DecisionAction
    path_dependent: bool
    state_identity: str | None = None
    feedback_cursor: str | None = None
    proposed_memory: dict[str, object] | None = None
    expected_memory_version: int | None = None
    diagnostics: tuple[str, ...] = ()
    accesses: tuple[AccessRecord, ...] = ()
    state_accesses: tuple[StateAccessRecord, ...] = ()
    feedback_accesses: tuple[FeedbackAccessRecord, ...] = ()
    performance_accesses: tuple[SessionPerformanceAccessRecord, ...] = ()
    memory_accesses: tuple[MemoryAccessRecord, ...] = ()


class StrategyResultV1(_StrategyResultFields):
    """Exact reader for the persisted strategy_result:v1 payload."""


class StrategySourceStateLineage(QlibxModel):
    """One original stateful Strategy result carried through frozen composition."""

    source_artifact_id: str = Field(min_length=1)
    source_artifact_schema_version: Literal[1, 2]
    source_invocation_id: str = Field(min_length=1)
    source_strategy_id: str = Field(min_length=1)
    declared_state_identity: str = Field(min_length=1)
    declared_feedback_cursor: str | None = None
    state_accesses: tuple[StateAccessRecord, ...] = ()
    feedback_accesses: tuple[FeedbackAccessRecord, ...] = ()
    performance_accesses: tuple[SessionPerformanceAccessRecord, ...] = ()
    memory_accesses: tuple[MemoryAccessRecord, ...] = ()

    @model_validator(mode="after")
    def validate_observed_state(self) -> "StrategySourceStateLineage":
        if not strategy_accesses_are_path_dependent(
            state_accesses=self.state_accesses,
            feedback_accesses=self.feedback_accesses,
            performance_accesses=self.performance_accesses,
            memory_accesses=self.memory_accesses,
        ):
            raise ValueError("source lineage requires package-observed stateful access")
        return self


class StrategyResult(_StrategyResultFields):
    """Canonical strategy_result:v2 payload with transitive source-state lineage."""

    source_state_lineage: tuple[StrategySourceStateLineage, ...] = ()

    @model_validator(mode="after")
    def validate_path_lineage(self) -> "StrategyResult":
        observed_direct = strategy_accesses_are_path_dependent(
            state_accesses=self.state_accesses,
            feedback_accesses=self.feedback_accesses,
            performance_accesses=self.performance_accesses,
            memory_accesses=self.memory_accesses,
        )
        if observed_direct and not self.state_identity:
            raise ValueError("direct path dependence requires state_identity")
        if not observed_direct and (
            self.state_identity is not None or self.feedback_cursor is not None
        ):
            raise ValueError("state_identity and feedback_cursor describe direct state only")
        expected_path_dependent = observed_direct or bool(self.source_state_lineage)
        if self.path_dependent is not expected_path_dependent:
            raise ValueError("path_dependent must match direct or inherited state evidence")
        source_ids = tuple(lineage.source_artifact_id for lineage in self.source_state_lineage)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_state_lineage artifact IDs must be unique")
        if source_ids != tuple(sorted(source_ids)):
            raise ValueError("source_state_lineage must be sorted by source artifact ID")
        return self


def strategy_accesses_are_path_dependent(
    *,
    state_accesses: tuple[StateAccessRecord, ...],
    feedback_accesses: tuple[FeedbackAccessRecord, ...],
    performance_accesses: tuple[SessionPerformanceAccessRecord, ...],
    memory_accesses: tuple[MemoryAccessRecord, ...],
) -> bool:
    """Return package-observed direct path dependence for one Strategy computation."""

    return bool(state_accesses or feedback_accesses or performance_accesses or memory_accesses)


class StrategyComputationError(ValueError):
    """Raised by package Strategy operations for a typed computation failure."""

    def __init__(self, code: str, context: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.context = context


class StrategyPathDependenceError(ValueError):
    """Raised when a draft declaration contradicts observed direct state access."""


def validate_strategy_draft_path_dependence(
    draft: StrategyDraft,
    *,
    state_accesses: tuple[StateAccessRecord, ...],
    feedback_accesses: tuple[FeedbackAccessRecord, ...],
    performance_accesses: tuple[SessionPerformanceAccessRecord, ...],
    memory_accesses: tuple[MemoryAccessRecord, ...],
) -> bool:
    """Validate a Strategy's direct-state declaration against package-owned access evidence."""

    observed_direct = strategy_accesses_are_path_dependent(
        state_accesses=state_accesses,
        feedback_accesses=feedback_accesses,
        performance_accesses=performance_accesses,
        memory_accesses=memory_accesses,
    )
    if draft.path_dependent is not observed_direct:
        raise StrategyPathDependenceError(
            "StrategyDraft.path_dependent does not match observed direct stateful access"
        )
    if not observed_direct and (
        draft.state_identity is not None or draft.feedback_cursor is not None
    ):
        raise StrategyPathDependenceError(
            "direct state_identity and feedback_cursor require direct stateful access"
        )
    return observed_direct


class StrategyInvocation(QlibxModel):
    invocation_id: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)
    artifact_bindings: tuple[StrategyArtifactBinding, ...] = ()

    @model_validator(mode="after")
    def validate_artifact_binding_roles(self) -> "StrategyInvocation":
        roles = [binding.consumer_role for binding in self.artifact_bindings]
        if len(roles) != len(set(roles)):
            raise ValueError("Strategy artifact binding roles must be unique")
        return self


class StrategyOperation(Protocol):
    strategy_id: str

    def requirements(self) -> tuple[ComponentRequirement, ...]: ...

    def run(self, view: StrategyView) -> StrategyDraft: ...


class ArtifactAwareStrategyOperation(StrategyOperation, Protocol):
    def artifact_requirements(self) -> tuple[StrategyArtifactRequirement, ...]: ...
