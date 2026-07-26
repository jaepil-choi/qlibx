from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from kwam_qlib_backend.constraint_optimization import (
    CvxpyIntentTrackingOptimizer,
    LinearConstraintSpec,
    OptimizationProblem,
    PostSolveValidator,
)


def _problem() -> OptimizationProblem:
    physical = pd.Index(["A", "K200_ETF"])
    constituents = pd.Index(["A", "B"])
    return OptimizationProblem(
        desired_active_exposure=pd.Series([0.1, -0.1], index=constituents),
        benchmark_weight=pd.Series([0.6, 0.4], index=constituents),
        current_physical_weight=pd.Series([0.2, 0.6], index=physical),
        current_cash_weight=0.2,
        lookthrough_matrix=pd.DataFrame(
            [[1.0, 0.5], [0.0, 0.5]],
            index=constituents,
            columns=physical,
        ),
        tradable=pd.Series(True, index=physical),
        lower_bounds=pd.Series(0.0, index=physical),
        upper_bounds=pd.Series(1.0, index=physical),
        transaction_cost=pd.Series(0.0, index=physical),
        constraints=(
            LinearConstraintSpec(
                name="direct_cap",
                coefficients=pd.Series([1.0, 0.0], index=physical),
                upper=0.3,
            ),
        ),
    )


def test_cvxpy_optimizer_returns_valid_physical_and_lookthrough_targets() -> None:
    problem = _problem()

    result = CvxpyIntentTrackingOptimizer().optimize(problem)

    assert result.status == "optimal"
    assert result.validation_passed
    assert result.physical_target_weight is not None
    assert result.lookthrough_exposure is not None
    assert result.cash_target_weight is not None
    pd.testing.assert_series_equal(
        result.lookthrough_exposure,
        problem.lookthrough_matrix @ result.physical_target_weight,
    )
    assert result.physical_target_weight["A"] <= 0.3 + 1e-7
    assert result.solver_metadata["cvxpy_version"]


def test_optimizer_rejects_misaligned_contract_axes() -> None:
    problem = _problem()

    with pytest.raises(ValueError, match="transaction_cost axis"):
        CvxpyIntentTrackingOptimizer().optimize(
            replace(
                problem,
                transaction_cost=pd.Series(
                    [0.0, 0.0], index=["K200_ETF", "A"]
                ),
            )
        )


def test_post_solve_validator_is_independent_of_solver_status() -> None:
    problem = _problem()
    invalid_target = pd.Series({"A": 0.8, "K200_ETF": 0.3})

    validation = PostSolveValidator().validate(
        problem, invalid_target, cash_target=0.0
    )

    assert not validation.passed
    assert "budget constraint violated" in validation.errors
    assert "hard constraint violated: direct_cap" in validation.errors
