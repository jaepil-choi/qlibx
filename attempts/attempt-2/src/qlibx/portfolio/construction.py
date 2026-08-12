"""Pure optional portfolio construction over immutable signed alpha."""

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from qlibx.domain import BudgetMode
from qlibx.models import QlibxModel


class ConstructionProfile(StrEnum):
    HYPOTHETICAL_SIGNED = "hypothetical_signed"
    EQUITY_LONG_ONLY = "equity_long_only"


class PortfolioWeight(QlibxModel):
    instrument: str = Field(min_length=1)
    weight: float

    @model_validator(mode="after")
    def validate_weight(self) -> "PortfolioWeight":
        if not math.isfinite(self.weight):
            raise ValueError("portfolio weight must be finite")
        return self


class PortfolioConstructionRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    source_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)
    profile: ConstructionProfile
    requested_budget: float = Field(gt=0)
    requested_budget_mode: BudgetMode = BudgetMode.FLEXIBLE
    normalization_policy: Literal[
        "preserve_source_residual", "renormalize_to_requested_budget"
    ] = "preserve_source_residual"


class PortfolioConstructionInput(QlibxModel):
    source_strategy_id: str = Field(min_length=1)
    weights: tuple[PortfolioWeight, ...]
    budget_mode: BudgetMode = BudgetMode.FIXED
    target_gross: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def validate_weights(self) -> "PortfolioConstructionInput":
        instruments = [entry.instrument for entry in self.weights]
        if not instruments:
            raise ValueError("portfolio construction requires signed alpha weights")
        if len(instruments) != len(set(instruments)):
            raise ValueError("portfolio construction weights must be unique")
        if sum(abs(entry.weight) for entry in self.weights) <= 0:
            raise ValueError("portfolio construction requires non-zero signed alpha")
        return self


class PortfolioConstructionResultV1(QlibxModel):
    portfolio_schema_version: int = 1
    invocation_id: str
    source_artifact_id: str
    source_strategy_id: str
    evaluation_time: datetime
    profile: ConstructionProfile
    original_weights: tuple[PortfolioWeight, ...]
    target_weights: tuple[PortfolioWeight, ...]
    requested_budget: float
    realized_gross: float
    realized_net: float
    cash_residual: float
    diagnostics: tuple[str, ...]


class PortfolioConstructionResult(PortfolioConstructionResultV1):
    portfolio_schema_version: Literal[2] = 2
    source_budget_mode: BudgetMode = BudgetMode.FIXED
    source_target_gross: float = 1.0
    requested_budget_mode: BudgetMode = BudgetMode.FLEXIBLE
    normalization_policy: Literal[
        "preserve_source_residual", "renormalize_to_requested_budget"
    ] = "preserve_source_residual"
    dropped_weights: tuple[PortfolioWeight, ...] = ()
    dropped_gross: float = Field(default=0.0, ge=0)
    renormalized: bool = False
    renormalization_scale: float = 1.0


class PortfolioConstructionError(ValueError):
    def __init__(self, code: str, context: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.context = context


def construct_portfolio(
    request: PortfolioConstructionRequest,
    source: PortfolioConstructionInput,
) -> PortfolioConstructionResult:
    if request.profile is ConstructionProfile.HYPOTHETICAL_SIGNED:
        selected = source.weights
        dropped = ()
        diagnostic = "signed directions preserved for hypothetical evaluation"
    else:
        selected = tuple(entry for entry in source.weights if entry.weight > 0)
        dropped = tuple(entry for entry in source.weights if entry.weight <= 0)
        if not selected:
            raise PortfolioConstructionError(
                "CONSTRUCTION_NO_LONG_CANDIDATES",
                {"source_strategy_id": source.source_strategy_id},
            )
        diagnostic = "negative signed alpha removed for equity long-only target"

    source_gross = sum(abs(entry.weight) for entry in source.weights)
    selected_gross = sum(abs(entry.weight) for entry in selected)
    source_utilization = source_gross / source.target_gross
    preserved_budget = request.requested_budget * source_utilization
    if request.normalization_policy == "renormalize_to_requested_budget":
        target_budget = request.requested_budget
        renormalized = not math.isclose(selected_gross, target_budget, abs_tol=1e-10)
    else:
        target_budget = preserved_budget * (selected_gross / source_gross)
        renormalized = False
    if (
        request.requested_budget_mode is BudgetMode.FIXED
        and request.normalization_policy == "preserve_source_residual"
        and not math.isclose(target_budget, request.requested_budget, abs_tol=1e-10)
    ):
        raise PortfolioConstructionError(
            "CONSTRUCTION_FIXED_BUDGET_INCOMPATIBLE",
            {
                "requested_budget": request.requested_budget,
                "preserved_budget": target_budget,
            },
        )
    scale = target_budget / selected_gross
    targets = tuple(
        PortfolioWeight(instrument=entry.instrument, weight=entry.weight * scale)
        for entry in selected
    )
    realized_gross = sum(abs(entry.weight) for entry in targets)
    realized_net = sum(entry.weight for entry in targets)
    return PortfolioConstructionResult(
        invocation_id=request.invocation_id,
        source_artifact_id=request.source_artifact_id,
        source_strategy_id=source.source_strategy_id,
        evaluation_time=request.evaluation_time,
        profile=request.profile,
        original_weights=source.weights,
        target_weights=targets,
        requested_budget=request.requested_budget,
        realized_gross=realized_gross,
        realized_net=realized_net,
        cash_residual=max(0.0, request.requested_budget - realized_gross),
        diagnostics=(diagnostic, f"construction_scale={scale:.12g}"),
        source_budget_mode=source.budget_mode,
        source_target_gross=source.target_gross,
        requested_budget_mode=request.requested_budget_mode,
        normalization_policy=request.normalization_policy,
        dropped_weights=dropped,
        dropped_gross=sum(abs(entry.weight) for entry in dropped),
        renormalized=renormalized,
        renormalization_scale=scale,
    )
