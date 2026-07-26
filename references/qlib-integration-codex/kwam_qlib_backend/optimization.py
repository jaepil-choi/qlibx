from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

from kwam_qlib_backend.constraint_optimization import (
    CvxpyIntentTrackingOptimizer,
    OptimizationProblem,
    OptimizationResult,
)


class OptimizationTargetPolicy:
    """Actual Qlib holding feedback으로 매 decision problem을 갱신합니다."""

    def __init__(
        self,
        optimizer: CvxpyIntentTrackingOptimizer,
        problem: OptimizationProblem,
    ) -> None:
        self.optimizer = optimizer
        self.problem = problem
        self.audit_rows: list[dict[str, Any]] = []

    def __call__(
        self, decision_date: pd.Timestamp, feedback: Mapping[str, Any]
    ) -> pd.Series:
        current = feedback.get("current_physical_weight")
        if not isinstance(current, pd.Series):
            raise TypeError("Qlib feedback must contain current_physical_weight Series")
        current = current.reindex(self.problem.current_physical_weight.index)
        if current.isna().any():
            raise ValueError("Qlib current holding feedback has incomplete physical axes")
        current_cash = float(feedback["current_cash_weight"])
        decision_problem = replace(
            self.problem,
            current_physical_weight=current.astype("float64"),
            current_cash_weight=current_cash,
        )
        result = self.optimizer.optimize(decision_problem)
        if result.status != "optimal" or result.physical_target_weight is None:
            raise RuntimeError(
                f"portfolio optimization did not produce a target: {result.status}"
            )
        self.audit_rows.append(
            _audit_row(decision_date, decision_problem, result)
        )
        return result.physical_target_weight.copy()


def _audit_row(
    decision_date: pd.Timestamp,
    problem: OptimizationProblem,
    result: OptimizationResult,
) -> dict[str, Any]:
    target = result.physical_target_weight
    if target is None:
        raise TypeError("optimal result must contain physical_target_weight")
    return {
        "decision_date": pd.Timestamp(decision_date),
        "optimizer_status": result.status,
        "current_physical_weight": problem.current_physical_weight.to_dict(),
        "current_cash_weight": float(problem.current_cash_weight),
        "optimized_target_weight": target.to_dict(),
        "validation_passed": bool(result.validation_passed),
    }
