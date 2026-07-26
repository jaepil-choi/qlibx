from __future__ import annotations

import pandas as pd
import pytest

from _acceptance_contract import MarketScenario


def test_booksize_uses_integer_units_and_keeps_rounding_cash(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(300.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        lot_size=pd.Series({"A": 1}),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )
    targets = pd.DataFrame(0.55, index=dates, columns=["A"])

    result = backend_harness.run_weight_targets(scenario, targets)

    assert result.decision_weight(dates[0], "A") == pytest.approx(0.55)
    assert result.position_quantity(dates[0], "A") == 1
    assert result.cash(dates[0]) == pytest.approx(700.0)
    assert result.nav(dates[0]) == pytest.approx(1_000.0)
    quantity_columns = ["requested_quantity"]
    for column in quantity_columns:
        assert pd.api.types.is_integer_dtype(result.orders()[column])
    assert pd.api.types.is_integer_dtype(result.positions()["held_quantity"])


def test_stock_and_etf_cost_policy_is_applied_to_actual_fills(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    instruments = ["A", "K200_ETF"]
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=instruments),
        universe=pd.DataFrame(True, index=dates, columns=instruments),
        asset_class=pd.Series({"A": "stock", "K200_ETF": "etf"}),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(
            1.0, index=dates, columns=instruments
        ),
        cost_policy={
            "stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.002},
            "etf": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0},
        },
    )
    targets = pd.DataFrame(
        [[0.5, 0.5], [0.0, 0.0]], index=dates, columns=instruments
    )

    result = backend_harness.run_weight_targets(scenario, targets)
    sells = result.fills(dates[1]).set_index("instrument_id")

    assert sells.loc["A", "trade_cost"] == pytest.approx(1.0)
    assert sells.loc["K200_ETF", "trade_cost"] == pytest.approx(0.0)
    assert result.account_daily().loc[dates[1], "trade_cost"] == pytest.approx(1.0)


def test_upstream_execution_and_mark_prices_drive_physical_valuation(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame({"A": [100.0, 110.0]}, index=dates),
        valuation_price=pd.DataFrame({"A": [110.0, 55.0]}, index=dates),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
    )
    targets = pd.DataFrame(1.0, index=dates, columns=["A"])

    result = backend_harness.run_weight_targets(scenario, targets)

    assert result.position_quantity(dates[0], "A") == 10
    assert result.position_quantity(dates[1], "A") == 10
    assert result.nav(dates[0]) == pytest.approx(1_100.0)
    assert result.nav(dates[1]) == pytest.approx(550.0)
    assert result.portfolio_return(dates[1]) == pytest.approx(-0.5)


def test_normalized_physical_unit_is_default_when_factor_is_omitted(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
    )

    result = backend_harness.run_weight_targets(
        scenario, pd.DataFrame(1.0, index=dates, columns=["A"])
    )

    assert result.position_quantity(dates[0], "A") == 10
    assert result.nav(dates[1]) == pytest.approx(1_000.0)


def test_non_unit_factor_is_rejected_as_upstream_contract_violation(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(
            {"A": [1.0, 2.0]}, index=dates
        ),
    )

    with pytest.raises(
        ValueError,
        match="corporate-action normalization belongs to upstream ETL",
    ):
        backend_harness.run_weight_targets(
            scenario, pd.DataFrame(1.0, index=dates, columns=["A"])
        )
