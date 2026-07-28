"""Package-owned CVXPY contract for benchmark-relative physical portfolios."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import cvxpy as cp
import numpy as np
import pandas as pd

OptimizationStatus = Literal["optimal", "infeasible", "solver_error"]


@dataclass(frozen=True, slots=True)
class LinearConstraint:
    """A named hard or penalized linear constraint on physical weight and cash."""

    name: str
    coefficients: pd.Series
    lower: float | None = None
    upper: float | None = None
    soft_penalty: float | None = None
    cash_coefficient: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("constraint name must not be empty")
        if self.lower is None and self.upper is None:
            raise ValueError(f"constraint {self.name} requires a lower or upper bound")
        if self.soft_penalty is not None and self.soft_penalty <= 0:
            raise ValueError(f"constraint {self.name} soft_penalty must be positive")
        if not np.isfinite(float(self.cash_coefficient)):
            raise ValueError(f"constraint {self.name} cash_coefficient must be finite")

    @property
    def hard(self) -> bool:
        return self.soft_penalty is None


@dataclass(frozen=True, slots=True)
class OptimizationProblem:
    desired_active_exposure: pd.Series
    benchmark_weight: pd.Series
    current_physical_weight: pd.Series
    current_cash_weight: float
    lookthrough_matrix: pd.DataFrame
    tradable: pd.Series
    lower_bounds: pd.Series
    upper_bounds: pd.Series
    transaction_cost: pd.Series
    constraints: tuple[LinearConstraint, ...] = ()
    turnover_penalty: float = 0.0
    risk_penalty: float = 0.0
    risk_covariance: pd.DataFrame | None = None
    cash_lower: float = 0.0
    cash_upper: float = 1.0


@dataclass(frozen=True, slots=True)
class ConstraintDiagnostic:
    name: str
    hard: bool
    value: float
    lower: float | None
    upper: float | None
    slack: float
    penalty: float
    satisfied: bool


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    status: OptimizationStatus
    physical_target_weight: pd.Series | None
    cash_target_weight: float | None
    lookthrough_exposure: pd.Series | None
    constraint_diagnostics: tuple[ConstraintDiagnostic, ...] = ()
    validation_passed: bool = False
    validation_errors: tuple[str, ...] = ()
    objective_value: float | None = None
    solver_metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OptimizerConfig:
    solver: str = "CLARABEL"
    validation_tolerance: float = 1e-7

    def __post_init__(self) -> None:
        if not self.solver:
            raise ValueError("solver must not be empty")
        if self.validation_tolerance <= 0:
            raise ValueError("validation_tolerance must be positive")


class PostSolveValidator:
    """Validate the materialized solution independently from CVXPY expressions."""

    def __init__(self, tolerance: float = 1e-7) -> None:
        if tolerance <= 0:
            raise ValueError("tolerance must be positive")
        self.tolerance = float(tolerance)

    def validate(
        self,
        problem: OptimizationProblem,
        physical_target: pd.Series,
        cash_target: float,
    ) -> ValidationResult:
        errors: list[str] = []
        tolerance = self.tolerance
        if abs(float(physical_target.sum()) + cash_target - 1.0) > tolerance:
            errors.append("budget constraint violated")
        if (problem.lower_bounds - physical_target).gt(tolerance).any():
            errors.append("physical lower bound violated")
        if (physical_target - problem.upper_bounds).gt(tolerance).any():
            errors.append("physical upper bound violated")
        if cash_target < problem.cash_lower - tolerance:
            errors.append("cash lower bound violated")
        if cash_target > problem.cash_upper + tolerance:
            errors.append("cash upper bound violated")
        frozen = ~problem.tradable.astype(bool)
        if (
            (physical_target.loc[frozen] - problem.current_physical_weight.loc[frozen])
            .abs()
            .gt(tolerance)
            .any()
        ):
            errors.append("frozen holding constraint violated")
        for constraint in problem.constraints:
            if not constraint.hard:
                continue
            value = _constraint_value(constraint, physical_target, cash_target)
            if constraint.lower is not None and value < constraint.lower - tolerance:
                errors.append(f"hard constraint violated: {constraint.name}")
            if constraint.upper is not None and value > constraint.upper + tolerance:
                errors.append(f"hard constraint violated: {constraint.name}")
        return ValidationResult(not errors, tuple(errors))


class CvxpyIntentTrackingOptimizer:
    """Track benchmark plus signed active intent with observable constraints."""

    def __init__(self, config: OptimizerConfig | None = None) -> None:
        self.config = config or OptimizerConfig()
        self.validator = PostSolveValidator(self.config.validation_tolerance)

    def optimize(self, problem: OptimizationProblem) -> OptimizationResult:
        normalized = _normalize_problem(problem)
        physical_axis = normalized.current_physical_weight.index
        constituent_axis = normalized.benchmark_weight.index
        target = cp.Variable(len(physical_axis), name="physical_target")
        cash = cp.Variable(name="cash_target")
        lookthrough = normalized.lookthrough_matrix.to_numpy(dtype="float64") @ target
        desired = (normalized.benchmark_weight + normalized.desired_active_exposure).to_numpy(
            dtype="float64"
        )
        trade = target - normalized.current_physical_weight.to_numpy(dtype="float64")

        objective = cp.sum_squares(lookthrough - desired)
        objective += normalized.turnover_penalty * cp.norm1(trade)
        objective += cp.sum(
            cp.multiply(
                normalized.transaction_cost.to_numpy(dtype="float64"),
                cp.abs(trade),
            )
        )
        if normalized.risk_penalty:
            covariance = normalized.risk_covariance
            if covariance is None:
                covariance = pd.DataFrame(
                    np.eye(len(constituent_axis)),
                    index=constituent_axis,
                    columns=constituent_axis,
                )
            active = lookthrough - normalized.benchmark_weight.to_numpy(dtype="float64")
            objective += normalized.risk_penalty * cp.quad_form(
                active,
                cp.psd_wrap(covariance.to_numpy(dtype="float64")),
            )

        constraints: list[cp.Constraint] = [
            cp.sum(target) + cash == 1.0,
            target >= normalized.lower_bounds.to_numpy(dtype="float64"),
            target <= normalized.upper_bounds.to_numpy(dtype="float64"),
            cash >= normalized.cash_lower,
            cash <= normalized.cash_upper,
        ]
        for position in np.flatnonzero(~normalized.tradable.to_numpy(dtype=bool)):
            constraints.append(
                target[position] == float(normalized.current_physical_weight.iloc[position])
            )
        for specification in normalized.constraints:
            expression = (
                specification.coefficients.to_numpy(dtype="float64") @ target
                + float(specification.cash_coefficient) * cash
            )
            if specification.hard:
                if specification.lower is not None:
                    constraints.append(expression >= specification.lower)
                if specification.upper is not None:
                    constraints.append(expression <= specification.upper)
                continue
            if specification.lower is not None:
                lower_slack = cp.Variable(
                    nonneg=True,
                    name=f"{specification.name}_lower_slack",
                )
                constraints.append(expression + lower_slack >= specification.lower)
                objective += float(specification.soft_penalty) * lower_slack
            if specification.upper is not None:
                upper_slack = cp.Variable(
                    nonneg=True,
                    name=f"{specification.name}_upper_slack",
                )
                constraints.append(expression - upper_slack <= specification.upper)
                objective += float(specification.soft_penalty) * upper_slack

        cvx_problem = cp.Problem(cp.Minimize(objective), constraints)
        try:
            objective_value = cvx_problem.solve(solver=self.config.solver)
        except cp.error.SolverError as error:
            return self._failure("solver_error", cvx_problem, str(error))
        if cvx_problem.status in {cp.INFEASIBLE, cp.INFEASIBLE_INACCURATE}:
            return self._failure("infeasible", cvx_problem)
        if cvx_problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE}:
            return self._failure(
                "solver_error",
                cvx_problem,
                f"unexpected solver status: {cvx_problem.status}",
            )
        if target.value is None or cash.value is None:
            return self._failure("solver_error", cvx_problem, "solver returned no solution")

        physical_target = pd.Series(
            np.asarray(target.value, dtype="float64"),
            index=physical_axis,
            dtype="float64",
        )
        cash_target = float(cash.value)
        exposure = pd.Series(
            normalized.lookthrough_matrix.to_numpy(dtype="float64")
            @ physical_target.to_numpy(dtype="float64"),
            index=constituent_axis,
            dtype="float64",
        )
        diagnostics = tuple(
            _constraint_diagnostic(
                item,
                physical_target,
                cash_target,
                self.config.validation_tolerance,
            )
            for item in normalized.constraints
        )
        validation = self.validator.validate(normalized, physical_target, cash_target)
        return OptimizationResult(
            status="optimal" if validation.passed else "solver_error",
            physical_target_weight=physical_target,
            cash_target_weight=cash_target,
            lookthrough_exposure=exposure,
            constraint_diagnostics=diagnostics,
            validation_passed=validation.passed,
            validation_errors=validation.errors,
            objective_value=float(objective_value),
            solver_metadata=_solver_metadata(cvx_problem, self.config.solver),
        )

    def _failure(
        self,
        status: Literal["infeasible", "solver_error"],
        problem: cp.Problem,
        error: str | None = None,
    ) -> OptimizationResult:
        metadata = _solver_metadata(problem, self.config.solver)
        if error is not None:
            metadata["error"] = error
        return OptimizationResult(
            status=status,
            physical_target_weight=None,
            cash_target_weight=None,
            lookthrough_exposure=None,
            solver_metadata=metadata,
        )


def _normalize_problem(problem: OptimizationProblem) -> OptimizationProblem:
    constituents = problem.lookthrough_matrix.index
    physical = problem.lookthrough_matrix.columns
    if constituents.has_duplicates or physical.has_duplicates:
        raise ValueError("lookthrough_matrix axes must be unique")
    series_by_axis = {
        "desired_active_exposure": (problem.desired_active_exposure, constituents),
        "benchmark_weight": (problem.benchmark_weight, constituents),
        "current_physical_weight": (problem.current_physical_weight, physical),
        "tradable": (problem.tradable, physical),
        "lower_bounds": (problem.lower_bounds, physical),
        "upper_bounds": (problem.upper_bounds, physical),
        "transaction_cost": (problem.transaction_cost, physical),
    }
    normalized: dict[str, pd.Series] = {}
    for name, (series, expected_index) in series_by_axis.items():
        if not isinstance(series, pd.Series) or not series.index.equals(expected_index):
            raise ValueError(f"{name} axis must match the optimization contract")
        normalized[name] = series.copy()
    for name in (
        "desired_active_exposure",
        "benchmark_weight",
        "current_physical_weight",
        "lower_bounds",
        "upper_bounds",
        "transaction_cost",
    ):
        values = normalized[name].astype("float64")
        if not np.isfinite(values.to_numpy()).all():
            raise ValueError(f"{name} must contain finite values")
        normalized[name] = values
    lookthrough = problem.lookthrough_matrix.astype("float64")
    if not np.isfinite(lookthrough.to_numpy()).all():
        raise ValueError("lookthrough_matrix must contain finite values")
    if (normalized["lower_bounds"] > normalized["upper_bounds"]).any():
        raise ValueError("physical lower bounds cannot exceed upper bounds")
    if (normalized["transaction_cost"] < 0).any():
        raise ValueError("transaction_cost must be non-negative")
    if problem.turnover_penalty < 0 or problem.risk_penalty < 0:
        raise ValueError("optimizer penalties must be non-negative")
    if not np.isfinite(
        np.asarray(
            [problem.current_cash_weight, problem.cash_lower, problem.cash_upper],
            dtype="float64",
        )
    ).all():
        raise ValueError("cash inputs must be finite")
    if problem.cash_lower > problem.cash_upper:
        raise ValueError("cash lower bound cannot exceed cash upper bound")

    constraints: list[LinearConstraint] = []
    names: set[str] = set()
    for item in problem.constraints:
        if item.name in names:
            raise ValueError(f"constraint names must be unique: {item.name}")
        names.add(item.name)
        if not item.coefficients.index.equals(physical):
            raise ValueError(f"constraint {item.name} coefficients must match physical axis")
        coefficients = item.coefficients.astype("float64")
        bounds = [value for value in (item.lower, item.upper) if value is not None]
        if not np.isfinite(coefficients.to_numpy()).all() or not np.isfinite(bounds).all():
            raise ValueError(f"constraint {item.name} must contain finite values")
        constraints.append(
            LinearConstraint(
                item.name,
                coefficients,
                item.lower,
                item.upper,
                item.soft_penalty,
                item.cash_coefficient,
            )
        )

    covariance = problem.risk_covariance
    if covariance is not None:
        if not covariance.index.equals(constituents) or not covariance.columns.equals(constituents):
            raise ValueError("risk_covariance axes must match constituent exposure")
        covariance = covariance.astype("float64")
        if not np.isfinite(covariance.to_numpy()).all():
            raise ValueError("risk_covariance must contain finite values")
        if not np.allclose(covariance, covariance.T, atol=1e-10):
            raise ValueError("risk_covariance must be symmetric")

    return OptimizationProblem(
        desired_active_exposure=normalized["desired_active_exposure"],
        benchmark_weight=normalized["benchmark_weight"],
        current_physical_weight=normalized["current_physical_weight"],
        current_cash_weight=float(problem.current_cash_weight),
        lookthrough_matrix=lookthrough,
        tradable=normalized["tradable"].astype(bool),
        lower_bounds=normalized["lower_bounds"],
        upper_bounds=normalized["upper_bounds"],
        transaction_cost=normalized["transaction_cost"],
        constraints=tuple(constraints),
        turnover_penalty=float(problem.turnover_penalty),
        risk_penalty=float(problem.risk_penalty),
        risk_covariance=covariance,
        cash_lower=float(problem.cash_lower),
        cash_upper=float(problem.cash_upper),
    )


def _constraint_value(
    constraint: LinearConstraint,
    physical_target: pd.Series,
    cash_target: float,
) -> float:
    return float(constraint.coefficients.dot(physical_target)) + (
        float(constraint.cash_coefficient) * cash_target
    )


def _constraint_diagnostic(
    constraint: LinearConstraint,
    physical_target: pd.Series,
    cash_target: float,
    tolerance: float,
) -> ConstraintDiagnostic:
    value = _constraint_value(constraint, physical_target, cash_target)
    lower_violation = 0.0 if constraint.lower is None else max(float(constraint.lower) - value, 0.0)
    upper_violation = 0.0 if constraint.upper is None else max(value - float(constraint.upper), 0.0)
    slack = lower_violation + upper_violation
    return ConstraintDiagnostic(
        name=constraint.name,
        hard=constraint.hard,
        value=value,
        lower=constraint.lower,
        upper=constraint.upper,
        slack=slack,
        penalty=(0.0 if constraint.soft_penalty is None else float(constraint.soft_penalty)),
        satisfied=slack <= tolerance,
    )


def _solver_metadata(problem: cp.Problem, solver: str) -> dict[str, object]:
    statistics = problem.solver_stats
    return {
        "solver": solver,
        "cvxpy_version": cp.__version__,
        "raw_status": problem.status,
        "num_iters": None if statistics is None else statistics.num_iters,
        "solve_time": None if statistics is None else statistics.solve_time,
    }


__all__ = [
    "ConstraintDiagnostic",
    "CvxpyIntentTrackingOptimizer",
    "LinearConstraint",
    "OptimizationProblem",
    "OptimizationResult",
    "OptimizationStatus",
    "OptimizerConfig",
    "PostSolveValidator",
    "ValidationResult",
]
