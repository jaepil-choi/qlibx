from __future__ import annotations

import pandas as pd
import pytest

from qlibx._vendor.qlib_engine.backtest_schema import EnhancedIndexConfig
from qlibx._vendor.qlib_engine.enhanced import EnhancedIndexTargetPolicy
from qlibx.portfolio import LinearConstraint, construct_enhanced_index


def test_public_portfolio_reports_named_constraint_and_infeasibility() -> None:
    common = {
        "benchmark_weight": pd.Series({"A": 0.5, "B": 0.4}),
        "active_weight": pd.Series({"A": 0.1, "B": 0.0}),
        "price": pd.Series({"A": 10.0, "B": 10.0}),
        "portfolio_value": 10_000.0,
    }
    constrained = construct_enhanced_index(
        **common,
        constraints=(
            LinearConstraint(
                "a_cap",
                pd.Series({"A": 1.0, "B": 0.0}),
                upper=0.55,
            ),
        ),
    )
    assert constrained.status == "soft_relaxed"
    assert constrained.physical_weight["A"] == pytest.approx(0.55)
    assert constrained.constraint_diagnostics[0].name == "a_cap"
    assert constrained.constraint_diagnostics[0].satisfied is True
    assert "constraint:a_cap" in constrained.binding_constraints
    assert constrained.solver_metadata["raw_status"] == "optimal"

    impossible = construct_enhanced_index(
        **common,
        upper_bounds=pd.Series({"A": 0.5, "B": 1.0}),
        constraints=(
            LinearConstraint(
                "impossible_a_floor",
                pd.Series({"A": 1.0, "B": 0.0}),
                lower=0.8,
            ),
        ),
    )
    assert impossible.status == "hard_infeasible"
    assert impossible.validation_passed is False
    assert impossible.solver_metadata["raw_status"] == "infeasible"


def test_solver_failure_is_an_explicit_result() -> None:
    result = construct_enhanced_index(
        benchmark_weight=pd.Series({"A": 0.8}),
        active_weight=pd.Series({"A": 0.0}),
        price=pd.Series({"A": 10.0}),
        portfolio_value=1_000.0,
        solver="NOT_A_SOLVER",
    )
    assert result.status == "solver_failed"
    assert "error" in result.solver_metadata


def test_vendor_batch_policy_uses_package_owned_optimizer() -> None:
    date = pd.Timestamp("2025-01-02")
    policy = EnhancedIndexTargetPolicy(
        desired_active_exposure=pd.DataFrame({"A": [0.1]}, index=[date]),
        benchmark_weight=pd.DataFrame({"A": [0.8]}, index=[date]),
        physical_tradable=pd.DataFrame({"STOCK_A": [True]}, index=[date]),
        config=EnhancedIndexConfig(
            lookthrough={"A": {"STOCK_A": 1.0}},
            lower_bounds={"STOCK_A": 0.0},
            upper_bounds={"STOCK_A": 1.0},
            transaction_cost={"STOCK_A": 0.0},
            cash_lower=0.0,
            cash_upper=1.0,
        ),
    )
    target = policy(
        date,
        {
            "current_physical_weight": pd.Series({"STOCK_A": 0.0}),
            "current_cash_weight": 1.0,
        },
    )
    assert target["STOCK_A"] == pytest.approx(0.9)
    assert policy.daily_rows[0]["optimizer_status"] == "optimal"
    assert policy.daily_rows[0]["validation_passed"] is True
