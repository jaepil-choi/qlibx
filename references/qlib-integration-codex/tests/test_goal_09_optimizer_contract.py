from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from _acceptance_contract import (
    LinearConstraintInput,
    MarketScenario,
    OptimizationScenario,
)


def _scenario() -> OptimizationScenario:
    physical = ["A", "K200_ETF"]
    constituents = ["A", "B"]
    return OptimizationScenario(
        desired_active_exposure=pd.Series({"A": 0.0, "B": 0.0}),
        benchmark_weight=pd.Series({"A": 0.6, "B": 0.4}),
        current_physical_weight=pd.Series({"A": 0.2, "K200_ETF": 0.6}),
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
            LinearConstraintInput(
                name="direct_stock_cap",
                coefficients=pd.Series({"A": 1.0, "K200_ETF": 0.0}),
                upper=0.25,
            ),
        ),
    )


def _diagnostic(result, name: str):
    return next(item for item in result.constraint_diagnostics if item.name == name)


def test_optimizer_tracks_lookthrough_once_and_validates_hard_constraints(
    backend_harness,
) -> None:
    scenario = _scenario()

    result = backend_harness.optimize_portfolio(scenario)

    assert result.status == "optimal"
    assert result.validation_passed
    assert result.physical_target_weight is not None
    assert result.lookthrough_exposure is not None
    assert result.cash_target_weight is not None
    expected = scenario.lookthrough_matrix @ result.physical_target_weight
    pd.testing.assert_series_equal(result.lookthrough_exposure, expected)
    assert result.physical_target_weight["A"] <= 0.25 + 1e-7
    assert (
        result.physical_target_weight.sum() + result.cash_target_weight
        == pytest.approx(1.0)
    )
    assert _diagnostic(result, "direct_stock_cap").satisfied


def test_frozen_position_and_turnover_use_actual_current_holding(
    backend_harness,
) -> None:
    base = _scenario()
    frozen = replace(
        base,
        current_physical_weight=pd.Series({"A": 0.1, "K200_ETF": 0.4}),
        current_cash_weight=0.5,
        tradable=pd.Series({"A": True, "K200_ETF": False}),
        constraints=(),
    )

    frozen_result = backend_harness.optimize_portfolio(frozen)

    assert frozen_result.status == "optimal"
    assert frozen_result.physical_target_weight is not None
    assert frozen_result.physical_target_weight["K200_ETF"] == pytest.approx(0.4)

    turnover_aware = replace(
        base,
        desired_active_exposure=pd.Series({"A": 0.2, "B": -0.2}),
        constraints=(),
        turnover_penalty=10.0,
    )
    changed_current = replace(
        turnover_aware,
        current_physical_weight=pd.Series({"A": 0.0, "K200_ETF": 0.8}),
        current_cash_weight=0.2,
    )
    first = backend_harness.optimize_portfolio(turnover_aware)
    second = backend_harness.optimize_portfolio(changed_current)

    assert first.physical_target_weight is not None
    assert second.physical_target_weight is not None
    assert not first.physical_target_weight.equals(second.physical_target_weight)
    assert first.physical_target_weight["A"] > second.physical_target_weight["A"]


def test_soft_constraint_records_named_slack_and_penalty(backend_harness) -> None:
    base = _scenario()
    soft = replace(
        base,
        desired_active_exposure=pd.Series({"A": 0.3, "B": -0.3}),
        constraints=(
            LinearConstraintInput(
                name="soft_direct_zero",
                coefficients=pd.Series({"A": 1.0, "K200_ETF": 0.0}),
                upper=0.0,
                soft_penalty=0.01,
            ),
        ),
    )

    result = backend_harness.optimize_portfolio(soft)

    assert result.status == "optimal"
    diagnostic = _diagnostic(result, "soft_direct_zero")
    assert not diagnostic.hard
    assert diagnostic.slack > 0.0
    assert diagnostic.penalty == pytest.approx(0.01)


def test_infeasible_is_not_silently_relaxed(backend_harness) -> None:
    base = _scenario()
    coefficients = pd.Series({"A": 1.0, "K200_ETF": 0.0})
    infeasible = replace(
        base,
        constraints=(
            LinearConstraintInput(
                name="direct_min", coefficients=coefficients, lower=0.8
            ),
            LinearConstraintInput(
                name="direct_max", coefficients=coefficients, upper=0.2
            ),
        ),
    )

    result = backend_harness.optimize_portfolio(infeasible)

    assert result.status == "infeasible"
    assert result.physical_target_weight is None
    assert not result.validation_passed


def test_solver_failure_is_distinct_from_infeasibility(backend_harness) -> None:
    result = backend_harness.optimize_portfolio(
        replace(_scenario(), solver="NOT_A_REAL_SOLVER")
    )

    assert result.status == "solver_error"
    assert result.physical_target_weight is None
    assert not result.validation_passed
    assert result.solver_metadata["solver"] == "NOT_A_REAL_SOLVER"


def test_actual_qlib_partial_fill_becomes_next_optimizer_current_holding(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    market = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        volume=pd.DataFrame({"A": [4.0, 1_000.0]}, index=dates),
        max_volume_participation=0.5,
    )
    optimization = OptimizationScenario(
        desired_active_exposure=pd.Series({"A": 0.0}),
        benchmark_weight=pd.Series({"A": 1.0}),
        current_physical_weight=pd.Series({"A": 0.0}),
        current_cash_weight=1.0,
        lookthrough_matrix=pd.DataFrame([[1.0]], index=["A"], columns=["A"]),
        tradable=pd.Series({"A": True}),
        lower_bounds=pd.Series({"A": 0.0}),
        upper_bounds=pd.Series({"A": 1.0}),
        transaction_cost=pd.Series({"A": 0.0}),
    )

    result = backend_harness.run_optimizer_feedback_loop(market, optimization)
    audit = result.state_audit().set_index("decision_date")

    assert result.fills(dates[0]).iloc[-1]["filled_quantity"] == 2
    assert audit.loc[dates[0], "optimized_target_weight"]["A"] > 0.99
    assert audit.loc[dates[1], "current_physical_weight"]["A"] == pytest.approx(0.2)
    assert audit.loc[dates[1], "current_cash_weight"] == pytest.approx(0.8)
