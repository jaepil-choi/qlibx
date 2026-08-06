"""MVP no-short and time-varying single-name-cap operations."""

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from qlibx.context import AccessRecord
from qlibx.models import QlibxModel
from qlibx.portfolio.construction import PortfolioConstructionResult, PortfolioWeight


class ConstraintDeclaration(QlibxModel):
    declaration_schema_version: int = 1
    declaration_id: str = Field(min_length=1)
    benchmark_weight_role: str = Field(min_length=1)
    single_name_floor: float = Field(gt=0, le=1)
    no_short: Literal[True] = True


class ExecutionLotInput(QlibxModel):
    instrument: str = Field(min_length=1)
    price: float = Field(gt=0)
    lot_size: float = Field(gt=0)
    current_quantity: float = Field(ge=0)


class ConstraintAdjustmentRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    source_portfolio_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)
    account_state_identity: str = Field(min_length=1)
    capital: float = Field(gt=0)
    lots: tuple[ExecutionLotInput, ...]

    @model_validator(mode="after")
    def validate_lots(self) -> "ConstraintAdjustmentRequest":
        instruments = [item.instrument for item in self.lots]
        if len(instruments) != len(set(instruments)):
            raise ValueError("execution lot inputs must have unique instruments")
        return self


class ConstraintValidationRequest(QlibxModel):
    invocation_id: str = Field(min_length=1)
    adjustment_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    config_fingerprint: str = Field(min_length=1)


class BenchmarkWeight(QlibxModel):
    instrument: str = Field(min_length=1)
    weight: float = Field(ge=0, le=1)


class ConstraintAdjustmentItem(QlibxModel):
    instrument: str
    original_weight: float
    benchmark_weight: float
    cap: float
    continuous_weight: float
    adjusted_weight: float
    continuous_quantity: float
    requested_delta_quantity: float
    rounded_delta_quantity: float
    projected_quantity: float
    before_excess: float = Field(ge=0)
    unresolved_excess: float = Field(ge=0)
    reasons: tuple[str, ...]


class ConstraintAdjustmentResult(QlibxModel):
    adjustment_schema_version: int = 1
    invocation_id: str
    declaration_id: str
    source_portfolio_artifact_id: str
    account_state_identity: str
    evaluation_time: datetime
    original_weights: tuple[PortfolioWeight, ...]
    adjusted_weights: tuple[PortfolioWeight, ...]
    items: tuple[ConstraintAdjustmentItem, ...]
    original_gross: float
    adjusted_gross: float
    cash_residual: float
    unresolved_excess: float
    accesses: tuple[AccessRecord, ...]


class ConstraintFinding(QlibxModel):
    instrument: str
    metric: str
    measured: float
    bound: float
    excess: float = Field(ge=0)
    passed: bool
    severity: str


class ConstraintValidationResult(QlibxModel):
    validation_schema_version: int = 1
    invocation_id: str
    declaration_id: str
    adjustment_artifact_id: str
    evaluation_time: datetime
    eligible: bool
    findings: tuple[ConstraintFinding, ...]
    accesses: tuple[AccessRecord, ...]


class ConstraintEvaluationError(ValueError):
    def __init__(self, code: str, context: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.context = context


def adjust_single_name_caps(
    request: ConstraintAdjustmentRequest,
    declaration: ConstraintDeclaration,
    source: PortfolioConstructionResult,
    benchmark: tuple[BenchmarkWeight, ...],
    accesses: tuple[AccessRecord, ...],
) -> ConstraintAdjustmentResult:
    benchmarks = {item.instrument: item.weight for item in benchmark}
    lots = {item.instrument: item for item in request.lots}
    instruments = {item.instrument for item in source.target_weights}
    missing_benchmark = sorted(instruments - benchmarks.keys())
    missing_lots = sorted(instruments - lots.keys())
    if missing_benchmark:
        raise ConstraintEvaluationError(
            "CONSTRAINT_BENCHMARK_COVERAGE_MISSING",
            {"instruments": missing_benchmark},
        )
    if missing_lots:
        raise ConstraintEvaluationError(
            "CONSTRAINT_EXECUTION_LOT_MISSING",
            {"instruments": missing_lots},
        )

    items: list[ConstraintAdjustmentItem] = []
    adjusted: list[PortfolioWeight] = []
    for target in source.target_weights:
        benchmark_weight = benchmarks[target.instrument]
        cap = max(declaration.single_name_floor, benchmark_weight)
        continuous = min(target.weight, cap)
        reasons: list[str] = []
        if declaration.no_short and continuous < 0:
            continuous = 0.0
            reasons.append("no_short")
        if target.weight > cap:
            reasons.append("single_name_cap")
        lot = lots[target.instrument]
        continuous_quantity = continuous * request.capital / lot.price
        requested_delta = continuous_quantity - lot.current_quantity
        rounded_delta = (
            math.copysign(
                math.floor((abs(requested_delta) + 1e-12) / lot.lot_size)
                * lot.lot_size,
                requested_delta,
            )
            if requested_delta != 0
            else 0.0
        )
        projected_quantity = lot.current_quantity + rounded_delta
        adjusted_weight = projected_quantity * lot.price / request.capital
        if not math.isclose(adjusted_weight, continuous, abs_tol=1e-15):
            reasons.append("order_delta_lot_floor")
        before_excess = max(0.0, target.weight - cap, -target.weight)
        unresolved_excess = max(0.0, adjusted_weight - cap, -adjusted_weight)
        items.append(
            ConstraintAdjustmentItem(
                instrument=target.instrument,
                original_weight=target.weight,
                benchmark_weight=benchmark_weight,
                cap=cap,
                continuous_weight=continuous,
                adjusted_weight=adjusted_weight,
                continuous_quantity=continuous_quantity,
                requested_delta_quantity=requested_delta,
                rounded_delta_quantity=rounded_delta,
                projected_quantity=projected_quantity,
                before_excess=before_excess,
                unresolved_excess=unresolved_excess,
                reasons=tuple(reasons),
            )
        )
        adjusted.append(
            PortfolioWeight(instrument=target.instrument, weight=adjusted_weight)
        )

    original_gross = sum(abs(item.weight) for item in source.target_weights)
    adjusted_gross = sum(abs(item.weight) for item in adjusted)
    return ConstraintAdjustmentResult(
        invocation_id=request.invocation_id,
        declaration_id=declaration.declaration_id,
        source_portfolio_artifact_id=request.source_portfolio_artifact_id,
        account_state_identity=request.account_state_identity,
        evaluation_time=request.evaluation_time,
        original_weights=source.target_weights,
        adjusted_weights=tuple(adjusted),
        items=tuple(items),
        original_gross=original_gross,
        adjusted_gross=adjusted_gross,
        cash_residual=max(0.0, source.requested_budget - adjusted_gross),
        unresolved_excess=sum(item.unresolved_excess for item in items),
        accesses=accesses,
    )


def validate_single_name_caps(
    request: ConstraintValidationRequest,
    declaration: ConstraintDeclaration,
    adjustment: ConstraintAdjustmentResult,
    benchmark: tuple[BenchmarkWeight, ...],
    accesses: tuple[AccessRecord, ...],
) -> ConstraintValidationResult:
    if adjustment.declaration_id != declaration.declaration_id:
        raise ConstraintEvaluationError(
            "CONSTRAINT_DECLARATION_MISMATCH",
            {
                "adjustment_declaration_id": adjustment.declaration_id,
                "validation_declaration_id": declaration.declaration_id,
            },
        )
    if adjustment.evaluation_time != request.evaluation_time:
        raise ConstraintEvaluationError(
            "CONSTRAINT_CUTOFF_MISMATCH",
            {
                "adjustment_evaluation_time": adjustment.evaluation_time.isoformat(),
                "validation_evaluation_time": request.evaluation_time.isoformat(),
            },
        )
    benchmarks = {item.instrument: item.weight for item in benchmark}
    missing = sorted(
        {item.instrument for item in adjustment.adjusted_weights} - benchmarks.keys()
    )
    if missing:
        raise ConstraintEvaluationError(
            "CONSTRAINT_BENCHMARK_COVERAGE_MISSING",
            {"instruments": missing},
        )
    findings: list[ConstraintFinding] = []
    for target in adjustment.adjusted_weights:
        cap = max(declaration.single_name_floor, benchmarks[target.instrument])
        short_excess = max(0.0, -target.weight)
        cap_excess = max(0.0, target.weight - cap)
        findings.extend(
            (
                ConstraintFinding(
                    instrument=target.instrument,
                    metric="no_short",
                    measured=target.weight,
                    bound=0.0,
                    excess=short_excess,
                    passed=short_excess == 0.0,
                    severity="error",
                ),
                ConstraintFinding(
                    instrument=target.instrument,
                    metric="single_name_cap",
                    measured=target.weight,
                    bound=cap,
                    excess=cap_excess,
                    passed=cap_excess == 0.0,
                    severity="error",
                ),
            )
        )
    return ConstraintValidationResult(
        invocation_id=request.invocation_id,
        declaration_id=declaration.declaration_id,
        adjustment_artifact_id=request.adjustment_artifact_id,
        evaluation_time=request.evaluation_time,
        eligible=all(item.passed for item in findings),
        findings=tuple(findings),
        accesses=accesses,
    )
