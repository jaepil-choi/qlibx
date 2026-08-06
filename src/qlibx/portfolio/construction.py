"""Pure optional portfolio construction over immutable signed alpha."""

import math
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

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


class PortfolioConstructionInput(QlibxModel):
    source_strategy_id: str = Field(min_length=1)
    weights: tuple[PortfolioWeight, ...]

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


class PortfolioConstructionResult(QlibxModel):
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
        diagnostic = "signed directions preserved for hypothetical evaluation"
    else:
        selected = tuple(entry for entry in source.weights if entry.weight > 0)
        if not selected:
            raise PortfolioConstructionError(
                "CONSTRUCTION_NO_LONG_CANDIDATES",
                {"source_strategy_id": source.source_strategy_id},
            )
        diagnostic = "negative signed alpha removed for equity long-only target"

    selected_gross = sum(abs(entry.weight) for entry in selected)
    scale = request.requested_budget / selected_gross
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
    )
