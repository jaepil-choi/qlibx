from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from .backtest_schema import EnhancedIndexConfig


class EnhancedIndexTargetPolicy:
    """Stored signed intent를 Goal 9 optimizer의 physical target으로 변환합니다."""

    def __init__(
        self,
        *,
        desired_active_exposure: pd.DataFrame,
        benchmark_weight: pd.DataFrame,
        physical_tradable: pd.DataFrame,
        config: EnhancedIndexConfig,
    ) -> None:
        from kwam_qlib_backend.constraint_optimization import (
            CvxpyIntentTrackingOptimizer,
            OptimizerConfig,
        )

        self.desired_active_exposure = desired_active_exposure
        self.benchmark_weight = benchmark_weight
        self.physical_tradable = physical_tradable
        self.config = config
        self.lookthrough = _lookthrough_matrix(
            config,
            constituents=desired_active_exposure.columns,
            physical=physical_tradable.columns,
        )
        self.lower_bounds = _physical_series(
            config.lower_bounds, physical_tradable.columns, "lower_bounds"
        )
        self.upper_bounds = _physical_series(
            config.upper_bounds, physical_tradable.columns, "upper_bounds"
        )
        self.transaction_cost = _physical_series(
            config.transaction_cost,
            physical_tradable.columns,
            "transaction_cost",
        )
        self.optimizer = CvxpyIntentTrackingOptimizer(
            OptimizerConfig(solver=config.solver)
        )
        self.constituent_rows: list[dict[str, object]] = []
        self.physical_rows: list[dict[str, object]] = []
        self.daily_rows: list[dict[str, object]] = []

    def __call__(
        self,
        decision_date: pd.Timestamp,
        feedback: Mapping[str, Any],
    ) -> pd.Series:
        from kwam_qlib_backend.constraint_optimization import OptimizationProblem

        current = feedback.get("current_physical_weight")
        if not isinstance(current, pd.Series):
            raise TypeError("Qlib feedback must contain current_physical_weight Series")
        current = current.reindex(self.physical_tradable.columns)
        if current.isna().any():
            raise ValueError("Qlib current holding feedback has incomplete physical axes")
        date = pd.Timestamp(decision_date)
        desired = self.desired_active_exposure.loc[date]
        benchmark = self.benchmark_weight.loc[date]
        tradable = self.physical_tradable.loc[date].astype(bool)
        problem = OptimizationProblem(
            desired_active_exposure=desired,
            benchmark_weight=benchmark,
            current_physical_weight=current.astype("float64"),
            current_cash_weight=float(feedback["current_cash_weight"]),
            lookthrough_matrix=self.lookthrough,
            tradable=tradable,
            lower_bounds=self.lower_bounds,
            upper_bounds=self.upper_bounds,
            transaction_cost=self.transaction_cost,
            turnover_penalty=self.config.turnover_penalty,
            risk_penalty=self.config.risk_penalty,
            cash_lower=self.config.cash_lower,
            cash_upper=self.config.cash_upper,
        )
        result = self.optimizer.optimize(problem)
        if result.status != "optimal" or result.physical_target_weight is None:
            raise RuntimeError(
                f"enhanced-index optimization did not produce a target: {result.status}"
            )
        if result.lookthrough_exposure is None or result.cash_target_weight is None:
            raise RuntimeError("optimal enhanced-index result is incomplete")
        physical_target, cash_target, normalization_delta = (
            _normalize_numerical_solution(
                result.physical_target_weight,
                float(result.cash_target_weight),
                tolerance=self.optimizer.config.validation_tolerance,
            )
        )
        normalized_validation = self.optimizer.validator.validate(
            problem,
            physical_target,
            cash_target,
        )
        if not normalized_validation.passed:
            raise RuntimeError(
                "normalized enhanced-index target failed post-solve validation: "
                f"{normalized_validation.errors}"
            )
        lookthrough_exposure = self.lookthrough @ physical_target
        self._record(
            date=date,
            problem=problem,
            raw_physical_target=result.physical_target_weight,
            physical_target=physical_target,
            lookthrough_exposure=lookthrough_exposure,
            cash_target=cash_target,
            normalization_delta=normalization_delta,
            status=result.status,
            validation_passed=normalized_validation.passed,
        )
        return physical_target.copy()

    def _record(
        self,
        *,
        date: pd.Timestamp,
        problem: Any,
        raw_physical_target: pd.Series,
        physical_target: pd.Series,
        lookthrough_exposure: pd.Series,
        cash_target: float,
        normalization_delta: float,
        status: str,
        validation_passed: bool,
    ) -> None:
        self.daily_rows.append(
            {
                "trade_date": date,
                "optimizer_status": status,
                "current_cash_weight": float(problem.current_cash_weight),
                "cash_target_weight": cash_target,
                "numerical_normalization_max_abs": normalization_delta,
                "validation_passed": bool(validation_passed),
            }
        )
        for constituent in self.lookthrough.index:
            benchmark = float(problem.benchmark_weight[constituent])
            active = float(problem.desired_active_exposure[constituent])
            self.constituent_rows.append(
                {
                    "trade_date": date,
                    "constituent_id": str(constituent),
                    "benchmark_weight": benchmark,
                    "desired_active_exposure": active,
                    "desired_total_exposure": benchmark + active,
                    "realized_lookthrough_exposure": float(
                        lookthrough_exposure[constituent]
                    ),
                }
            )
        for instrument in self.lookthrough.columns:
            self.physical_rows.append(
                {
                    "trade_date": date,
                    "instrument_id": str(instrument),
                    "current_physical_weight": float(
                        problem.current_physical_weight[instrument]
                    ),
                    "raw_target_physical_weight": float(
                        raw_physical_target[instrument]
                    ),
                    "target_physical_weight": float(physical_target[instrument]),
                    "tradable": bool(problem.tradable[instrument]),
                    "lower_bound": float(problem.lower_bounds[instrument]),
                    "upper_bound": float(problem.upper_bounds[instrument]),
                    "transaction_cost": float(problem.transaction_cost[instrument]),
                }
            )


def _lookthrough_matrix(
    config: EnhancedIndexConfig,
    *,
    constituents: pd.Index,
    physical: pd.Index,
) -> pd.DataFrame:
    matrix = pd.DataFrame.from_dict(config.lookthrough, orient="index")
    matrix.index = matrix.index.astype(str)
    matrix.columns = matrix.columns.astype(str)
    if set(matrix.index) != set(constituents.astype(str)) or set(
        matrix.columns
    ) != set(physical.astype(str)):
        raise ValueError(
            "enhanced_index lookthrough axes must match alpha constituents and "
            "physical execution instruments"
        )
    matrix = matrix.reindex(
        index=constituents.astype(str),
        columns=physical.astype(str),
    ).astype("float64")
    if not np.isfinite(matrix.to_numpy()).all():
        raise ValueError("enhanced_index lookthrough must contain finite values")
    return matrix


def _physical_series(
    values: Mapping[str, float],
    physical: pd.Index,
    name: str,
) -> pd.Series:
    if set(values) != set(physical.astype(str)):
        raise ValueError(f"enhanced_index {name} axes must match physical instruments")
    series = pd.Series(values, dtype="float64").reindex(physical.astype(str))
    if not np.isfinite(series.to_numpy()).all():
        raise ValueError(f"enhanced_index {name} must contain finite values")
    return series


def _normalize_numerical_solution(
    physical_target: pd.Series,
    cash_target: float,
    *,
    tolerance: float,
) -> tuple[pd.Series, float, float]:
    raw = physical_target.astype("float64")
    if (raw < -tolerance).any() or cash_target < -tolerance:
        raise RuntimeError("optimizer returned materially negative target weights")
    target = raw.clip(lower=0.0)
    cash = max(0.0, float(cash_target))
    budget_error = abs(float(target.sum()) + cash - 1.0)
    if budget_error > tolerance:
        raise RuntimeError(
            "optimizer target exceeds numerical budget tolerance: "
            f"error={budget_error}, tolerance={tolerance}"
        )
    physical_budget = 1.0 - cash
    if float(target.sum()) <= 0.0:
        if physical_budget > tolerance:
            raise RuntimeError("optimizer returned no physical target for positive budget")
    else:
        target = target * (physical_budget / float(target.sum()))
    delta = max(
        float((target - raw).abs().max()),
        abs(cash - float(cash_target)),
    )
    return target, cash, delta
