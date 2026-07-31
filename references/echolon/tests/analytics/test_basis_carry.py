import pandas as pd
import pytest

from echolon.analytics.basis_carry import annualized_carry_cost, basis_series, daily_hedge_carry


def test_discount_basis_and_annualized_short_hedge_cost_anchor():
    dates = pd.to_datetime(["2023-01-03"])
    basis = basis_series(pd.Series([5_880.0], index=dates), pd.Series([6_000.0], index=dates))
    carry = annualized_carry_cost(basis, pd.Series([60.0], index=dates))

    assert basis.iloc[0] == pytest.approx(-0.02, abs=1e-9)
    assert carry.iloc[0] == pytest.approx(0.02 * 365.0 / 60.0, abs=1e-9)


def test_premium_basis_means_short_earns_carry():
    dates = pd.to_datetime(["2023-01-03"])
    basis = basis_series(pd.Series([6_120.0], index=dates), pd.Series([6_000.0], index=dates))
    carry = annualized_carry_cost(basis, pd.Series([60.0], index=dates))

    assert carry.iloc[0] < 0.0


def test_daily_hedge_carry_same_contract_anchor_and_roll_day_nan():
    dates = pd.to_datetime(["2023-01-03", "2023-01-04"])
    same = pd.DataFrame({"contract": ["IC2301", "IC2301"], "settle": [5880.0, 5910.0]}, index=dates)
    rolled = same.assign(contract=["IC2301", "IC2302"])
    spot = pd.Series([6000.0, 6000.0], index=dates)

    result = daily_hedge_carry(same, spot)
    assert list(result.columns) == ["contract", "hedge_carry_cost"]
    assert result.iloc[1]["hedge_carry_cost"] == pytest.approx(30.0 / 5880.0, abs=1e-12)
    assert pd.isna(daily_hedge_carry(rolled, spot).iloc[1]["hedge_carry_cost"])
