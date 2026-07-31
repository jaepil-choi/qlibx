from __future__ import annotations

import pandas as pd
import pytest

from qlibx.ensemble import combine_signed_weights
from qlibx.portfolio import construct_enhanced_index


def test_ensemble_nets_same_ticker_without_restoring_budget() -> None:
    date = pd.DatetimeIndex(["2025-01-01"])
    first = pd.DataFrame([[0.2, -0.1]], index=date, columns=["a", "b"])
    second = pd.DataFrame([[-0.05, 0.02]], index=date, columns=["a", "b"])
    result = combine_signed_weights(
        {"first": first, "second": second},
        coefficients={"first": 1.0, "second": 1.0},
    )
    assert result.combined.loc[date[0], "a"] == pytest.approx(0.15)
    assert result.combined.loc[date[0], "b"] == pytest.approx(-0.08)
    assert result.exposure.gross.iloc[0] == pytest.approx(0.23)


def test_enhanced_index_keeps_cash_and_reports_unimplemented_intent() -> None:
    result = construct_enhanced_index(
        benchmark_weight=pd.Series({"stock": 0.6, "etf": 0.2}),
        active_weight=pd.Series({"stock": 0.1, "etf": -0.05}),
        price=pd.Series({"stock": 100.0, "etf": 50.0}),
        portfolio_value=1_000.0,
        tradable=pd.Series({"stock": True, "etf": False}),
    )
    assert result.status == "soft_relaxed"
    assert result.physical_weight["stock"] == pytest.approx(0.7)
    assert result.physical_weight["etf"] == 0.0
    assert result.cash_weight == pytest.approx(0.3)
    assert result.passive_residual["etf"] == pytest.approx(0.2)
    assert result.unimplemented_active_weight["etf"] == pytest.approx(-0.05)


def test_negative_physical_target_is_explicitly_infeasible() -> None:
    result = construct_enhanced_index(
        benchmark_weight=pd.Series({"a": 0.05}),
        active_weight=pd.Series({"a": -0.10}),
        price=pd.Series({"a": 100.0}),
        portfolio_value=1_000.0,
    )
    assert result.status == "hard_infeasible"
    assert result.reason is not None


def test_marginal_contribution_ignores_cells_a_member_did_not_supply() -> None:
    date = pd.DatetimeIndex(["2025-01-01"])
    partial = pd.DataFrame([[1.0, pd.NA]], index=date, columns=["a", "b"], dtype="Float64")
    complete = pd.DataFrame([[1.0, 1.0]], index=date, columns=["a", "b"], dtype="Float64")
    result = combine_signed_weights({"partial": partial, "complete": complete})
    # Combined gross mass is 3.0; partial supplied 1.0 of it and complete supplied 2.0.
    # A missing cell must count as a zero contribution, not drop out of the norm.
    assert result.marginal_contribution["partial"] == pytest.approx(1 / 3)
    assert result.marginal_contribution["complete"] == pytest.approx(2 / 3)
