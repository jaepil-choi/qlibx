"""Direct Strategy contracts."""

import math
from datetime import datetime
from enum import StrEnum
from typing import Protocol

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
from qlibx.models import QlibxModel


class BudgetMode(StrEnum):
    FIXED = "fixed"
    FLEXIBLE = "flexible"


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


class StrategyResult(QlibxModel):
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


class StrategyInvocation(QlibxModel):
    invocation_id: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)


class StrategyOperation(Protocol):
    strategy_id: str

    def requirements(self) -> tuple[ComponentRequirement, ...]: ...

    def run(self, view: StrategyView) -> StrategyDraft: ...
