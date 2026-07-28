"""Benchmark-relative stock/ETF/cash construction with explicit look-through."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import pandas as pd

from .optimization import (
    ConstraintDiagnostic,
    CvxpyIntentTrackingOptimizer,
    LinearConstraint,
    OptimizationProblem,
    OptimizerConfig,
)

PortfolioStatus = Literal["optimal", "soft_relaxed", "hard_infeasible", "solver_failed"]


@dataclass(frozen=True, slots=True)
class EnhancedIndexResult:
    status: PortfolioStatus
    desired_active_weight: pd.Series
    desired_total_weight: pd.Series
    physical_weight: pd.Series
    target_quantity: pd.Series
    cash_weight: float
    lookthrough_exposure: pd.Series | None
    passive_exposure: pd.Series
    passive_residual: pd.Series
    etf_weight: pd.Series
    unimplemented_active_weight: pd.Series
    constraint_residual: pd.Series
    binding_constraints: tuple[str, ...]
    expected_trade_quantity: pd.Series
    expected_cost: float
    tracking_error: float
    solver_iterations: int
    constraint_diagnostics: tuple[ConstraintDiagnostic, ...]
    solver_metadata: dict[str, object]
    validation_passed: bool
    reason: str | None


def construct_enhanced_index(
    *,
    benchmark_weight: pd.Series,
    active_weight: pd.Series,
    price: pd.Series,
    portfolio_value: float,
    tradable: pd.Series | None = None,
    lot_size: pd.Series | None = None,
    instrument_type: pd.Series | None = None,
    current_quantity: pd.Series | None = None,
    current_cash: float | None = None,
    transaction_cost: pd.Series | None = None,
    lower_bounds: pd.Series | None = None,
    upper_bounds: pd.Series | None = None,
    constituent_exposure: pd.DataFrame | None = None,
    constituent_available_at: pd.Timestamp | None = None,
    decision_time: pd.Timestamp | None = None,
    cash_lower: float = 0.0,
    cash_upper: float = 1.0,
    tracking_tolerance: float = 1e-7,
    allow_soft_relaxation: bool = True,
    constraints: tuple[LinearConstraint, ...] = (),
    turnover_penalty: float = 0.0,
    risk_penalty: float = 0.0,
    risk_covariance: pd.DataFrame | None = None,
    solver: str = "CLARABEL",
) -> EnhancedIndexResult:
    """Construct physical targets without inventing ETF constituents or residual bets."""
    if portfolio_value <= 0:
        raise ValueError("portfolio_value must be positive")
    if not 0 <= cash_lower <= cash_upper <= 1:
        raise ValueError("cash bounds must satisfy 0 <= lower <= upper <= 1")
    if tracking_tolerance < 0:
        raise ValueError("tracking_tolerance must be non-negative")
    desired_index = benchmark_weight.index.union(active_weight.index)
    benchmark = benchmark_weight.reindex(desired_index).fillna(0.0).astype("float64")
    active = active_weight.reindex(desired_index).fillna(0.0).astype("float64")
    desired = benchmark.add(active)
    if desired.lt(-1e-12).any():
        return _infeasible(
            benchmark,
            active,
            desired,
            price.index,
            "benchmark plus active intent requires negative constituent exposure",
        )
    if float(desired.sum()) > 1.0 - cash_lower + 1e-12:
        return _infeasible(
            benchmark,
            active,
            desired,
            price.index,
            "desired exposure exceeds available capital and cash lower bound",
        )

    physical_instruments = price.index
    prices = price.astype("float64")
    if prices.index.has_duplicates or prices.isna().any() or prices.le(0).any():
        raise ValueError("price must uniquely cover every positive-price physical instrument")
    types = (
        pd.Series("stock", index=physical_instruments, dtype="string")
        if instrument_type is None
        else instrument_type.reindex(physical_instruments).astype("string")
    )
    if types.isna().any() or not types.isin(["stock", "etf"]).all():
        raise ValueError("instrument_type must explicitly be stock or etf")
    lots = (
        pd.Series(1, index=physical_instruments, dtype="int64")
        if lot_size is None
        else lot_size.reindex(physical_instruments).astype("int64")
    )
    if lots.isna().any() or lots.le(0).any():
        raise ValueError("lot_size must be present and positive for every physical instrument")
    available = (
        pd.Series(True, index=physical_instruments)
        if tradable is None
        else tradable.reindex(physical_instruments).fillna(False).astype(bool)
    )
    lower = (
        pd.Series(0.0, index=physical_instruments)
        if lower_bounds is None
        else lower_bounds.reindex(physical_instruments).astype("float64")
    )
    upper = (
        pd.Series(1.0, index=physical_instruments)
        if upper_bounds is None
        else upper_bounds.reindex(physical_instruments).astype("float64")
    )
    if lower.isna().any() or upper.isna().any() or lower.lt(0).any() or lower.gt(upper).any():
        raise ValueError("physical lower/upper bounds are incomplete or incompatible")
    costs = (
        pd.Series(0.0, index=physical_instruments)
        if transaction_cost is None
        else transaction_cost.reindex(physical_instruments).astype("float64")
    )
    if costs.isna().any() or costs.lt(0).any():
        raise ValueError("transaction_cost must be finite and non-negative")
    current = (
        pd.Series(0, index=physical_instruments, dtype="int64")
        if current_quantity is None
        else current_quantity.reindex(physical_instruments).fillna(0).astype("int64")
    )
    current_weight = current.mul(prices).div(portfolio_value)
    current_cash_weight = (
        max(0.0, 1.0 - float(current_weight.sum()))
        if current_cash is None
        else float(current_cash) / float(portfolio_value)
    )
    matrix = _exposure_matrix(
        desired,
        physical_instruments,
        constituent_exposure,
        constituent_available_at,
        decision_time,
    )
    problem = OptimizationProblem(
        desired_active_exposure=active,
        benchmark_weight=benchmark,
        current_physical_weight=current_weight,
        current_cash_weight=current_cash_weight,
        lookthrough_matrix=matrix,
        tradable=available,
        lower_bounds=lower,
        upper_bounds=upper,
        transaction_cost=costs,
        constraints=constraints,
        turnover_penalty=turnover_penalty,
        risk_penalty=risk_penalty,
        risk_covariance=risk_covariance,
        cash_lower=cash_lower,
        cash_upper=cash_upper,
    )
    optimizer = CvxpyIntentTrackingOptimizer(
        OptimizerConfig(solver=solver, validation_tolerance=max(tracking_tolerance, 1e-9))
    )
    optimized = optimizer.optimize(problem)
    if optimized.status != "optimal" or optimized.physical_target_weight is None:
        return _optimization_failure(
            benchmark,
            active,
            desired,
            physical_instruments,
            optimized.status,
            optimized.solver_metadata,
        )
    target_weight = optimized.physical_target_weight
    iterations_value = optimized.solver_metadata.get("num_iters")
    iterations = 0 if iterations_value is None else int(iterations_value)
    target_weight = target_weight.clip(lower=lower, upper=upper)
    target_weight = target_weight.where(available, current_weight)
    if float(target_weight.sum()) > 1.0 - cash_lower + 1e-10:
        scale = (1.0 - cash_lower) / float(target_weight.sum())
        target_weight = target_weight.mul(scale)
    raw_quantity = target_weight.mul(portfolio_value).div(prices)
    raw_lots = raw_quantity.div(lots)
    nearest_lots = raw_lots.round()
    stable_lots = raw_lots.where(raw_lots.sub(nearest_lots).abs().gt(1e-5), nearest_lots)
    quantity = stable_lots.floordiv(1).mul(lots).astype("int64")
    physical = quantity.mul(prices).div(portfolio_value)
    cash_weight = 1.0 - float(physical.sum())
    lookthrough = matrix.dot(physical)
    residual = desired.sub(lookthrough)
    tracking_error = float(residual.abs().max()) if len(residual) else 0.0
    passive_implemented = lookthrough.where(lookthrough.le(benchmark), benchmark)
    passive_residual = benchmark.sub(passive_implemented)
    unimplemented = residual.sub(passive_residual)
    trade_quantity = quantity.sub(current)
    expected_cost = float(trade_quantity.abs().mul(prices).mul(costs).sum())
    bindings = _bindings(
        physical,
        lower,
        upper,
        available,
        cash_weight,
        cash_lower,
        cash_upper,
        optimized.constraint_diagnostics,
    )
    validation = optimizer.validator.validate(problem, physical, cash_weight)
    hard_valid = validation.passed
    soft_constraint_relaxed = any(
        not item.hard and not item.satisfied for item in optimized.constraint_diagnostics
    )
    if not hard_valid:
        status: PortfolioStatus = "hard_infeasible"
        reason = "rounded physical target violates a hard bound"
    elif soft_constraint_relaxed:
        status = "soft_relaxed"
        reason = "one or more penalized constraints were relaxed"
    elif tracking_error <= tracking_tolerance:
        status = "optimal"
        reason = None
    elif allow_soft_relaxation:
        status = "soft_relaxed"
        reason = "tracking tolerance relaxed; residual remains explicitly unimplemented"
    else:
        status = "hard_infeasible"
        reason = "tracking tolerance cannot be satisfied under hard physical constraints"
    etf_weight = physical.where(types.eq("etf"), 0.0)
    return EnhancedIndexResult(
        status=status,
        desired_active_weight=active,
        desired_total_weight=desired,
        physical_weight=physical,
        target_quantity=quantity,
        cash_weight=cash_weight,
        lookthrough_exposure=(None if constituent_exposure is None else lookthrough),
        passive_exposure=benchmark,
        passive_residual=passive_residual,
        etf_weight=etf_weight,
        unimplemented_active_weight=unimplemented,
        constraint_residual=residual,
        binding_constraints=bindings,
        expected_trade_quantity=trade_quantity,
        expected_cost=expected_cost,
        tracking_error=tracking_error,
        solver_iterations=iterations,
        constraint_diagnostics=optimized.constraint_diagnostics,
        solver_metadata=optimized.solver_metadata,
        validation_passed=hard_valid,
        reason=reason,
    )


def _exposure_matrix(
    desired: pd.Series,
    physical_instruments: pd.Index,
    constituent_exposure: pd.DataFrame | None,
    constituent_available_at: pd.Timestamp | None,
    decision_time: pd.Timestamp | None,
) -> pd.DataFrame:
    if constituent_exposure is None:
        return pd.DataFrame(
            [
                [1.0 if constituent == instrument else 0.0 for instrument in physical_instruments]
                for constituent in desired.index
            ],
            index=desired.index,
            columns=physical_instruments,
        )
    if constituent_available_at is None or decision_time is None:
        raise ValueError("ETF look-through requires point-in-time availability and decision time")
    if pd.Timestamp(constituent_available_at) > pd.Timestamp(decision_time):
        raise ValueError("ETF constituent data was not available at decision time")
    if set(constituent_exposure.index) != set(desired.index):
        raise ValueError("constituent exposure axis is incompatible with desired exposure")
    if set(constituent_exposure.columns) != set(physical_instruments):
        raise ValueError("constituent exposure does not cover every physical instrument")
    matrix = constituent_exposure.reindex(
        index=desired.index,
        columns=physical_instruments,
    ).astype("float64")
    if matrix.isna().any().any():
        raise ValueError("constituent exposure contains missing values")
    return matrix


def _bindings(
    physical: pd.Series,
    lower: pd.Series,
    upper: pd.Series,
    tradable: pd.Series,
    cash: float,
    cash_lower: float,
    cash_upper: float,
    diagnostics: tuple[ConstraintDiagnostic, ...],
) -> tuple[str, ...]:
    output: list[str] = []
    output.extend(f"lower:{name}" for name in physical.index[physical.sub(lower).abs().le(1e-10)])
    output.extend(f"upper:{name}" for name in physical.index[physical.sub(upper).abs().le(1e-10)])
    output.extend(f"untradable:{name}" for name in tradable.index[~tradable])
    if abs(cash - cash_lower) <= 1e-10:
        output.append("cash_lower")
    if abs(cash - cash_upper) <= 1e-10:
        output.append("cash_upper")
    for item in diagnostics:
        at_lower = item.lower is not None and abs(item.value - item.lower) <= 1e-7
        at_upper = item.upper is not None and abs(item.value - item.upper) <= 1e-7
        if at_lower or at_upper or item.slack > 1e-7:
            output.append(f"constraint:{item.name}")
    return tuple(output)


def _infeasible(
    benchmark: pd.Series,
    active: pd.Series,
    desired: pd.Series,
    instruments: pd.Index,
    reason: str,
) -> EnhancedIndexResult:
    zero_weight = pd.Series(0.0, index=instruments)
    zero_quantity = pd.Series(0, index=instruments, dtype="int64")
    return EnhancedIndexResult(
        status="hard_infeasible",
        desired_active_weight=active,
        desired_total_weight=desired,
        physical_weight=zero_weight,
        target_quantity=zero_quantity,
        cash_weight=1.0,
        lookthrough_exposure=None,
        passive_exposure=benchmark,
        passive_residual=benchmark,
        etf_weight=zero_weight,
        unimplemented_active_weight=active,
        constraint_residual=desired,
        binding_constraints=(),
        expected_trade_quantity=zero_quantity,
        expected_cost=0.0,
        tracking_error=float(desired.abs().max()) if len(desired) else 0.0,
        solver_iterations=0,
        constraint_diagnostics=(),
        solver_metadata={},
        validation_passed=False,
        reason=reason,
    )


def _optimization_failure(
    benchmark: pd.Series,
    active: pd.Series,
    desired: pd.Series,
    instruments: pd.Index,
    status: str,
    metadata: dict[str, object],
) -> EnhancedIndexResult:
    result = _infeasible(
        benchmark,
        active,
        desired,
        instruments,
        (
            "enhanced-index optimization is infeasible"
            if status == "infeasible"
            else "enhanced-index solver failed"
        ),
    )
    return replace(
        result,
        status="hard_infeasible" if status == "infeasible" else "solver_failed",
        solver_metadata=metadata,
    )


__all__ = [
    "ConstraintDiagnostic",
    "EnhancedIndexResult",
    "LinearConstraint",
    "PortfolioStatus",
    "construct_enhanced_index",
]
