from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from _acceptance_contract import MarketScenario
from kwam_qlib_backend.backend import _validate_account_reconciliation


def test_account_reconciliation_tolerance_scales_with_large_nav() -> None:
    _validate_account_reconciliation(
        nav=100_000_000.00000003,
        cash=50_000_000.0,
        position_value=50_000_000.0,
        tolerance=1e-8,
    )

    with pytest.raises(RuntimeError, match="reconciliation.*tolerance"):
        _validate_account_reconciliation(
            nav=100_000_000.001,
            cash=50_000_000.0,
            position_value=50_000_000.0,
            tolerance=1e-8,
        )


def test_volume_and_cash_clipping_have_engine_stage_diagnostics(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    volume_scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        volume=pd.DataFrame({"A": [4.0, 1_000.0]}, index=dates),
        max_volume_participation=0.5,
    )
    target = pd.DataFrame(1.0, index=dates, columns=["A"])

    volume_result = backend_harness.run_weight_targets(volume_scenario, target)
    volume_fill = volume_result.fills(dates[0]).iloc[-1]

    assert volume_fill["reason"] == "partial_fill"
    assert volume_fill["reason_code"] == "volume_limited"
    assert volume_fill["quantity_after_tradability"] == 10
    assert volume_fill["quantity_after_volume"] == 2
    assert volume_fill["quantity_after_cash"] == 2
    assert volume_fill["quantity_after_lot"] == 2
    assert volume_fill["filled_quantity"] == 2

    cash_scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        lot_size=pd.Series({"A": 1}),
        cost_policy={
            "stock": {"buy_rate": 0.10, "sell_rate": 0.0, "sell_tax": 0.0}
        },
    )

    cash_result = backend_harness.run_weight_targets(cash_scenario, target)
    cash_fill = cash_result.fills(dates[0]).iloc[-1]

    assert cash_fill["reason_code"] == "cash_limited"
    assert cash_fill["quantity_after_volume"] == 10
    assert cash_fill["quantity_after_cash"] == pytest.approx(100.0 / 11.0)
    assert cash_fill["quantity_after_lot"] == 9
    assert cash_fill["filled_quantity"] == 9
    assert cash_result.position_quantity(dates[0], "A") == 9
    assert cash_result.backend_evidence()["account_reconciliation_error"] <= 1e-8


def test_target_lot_rounding_is_explicit_and_qlib_position_stays_integral(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=1)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(300.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        lot_size=pd.Series({"A": 2}),
    )

    result = backend_harness.run_weight_targets(
        scenario, pd.DataFrame(1.0, index=dates, columns=["A"])
    )
    order = result.orders(dates[0]).iloc[-1]

    assert order["raw_target_quantity"] == pytest.approx(10.0 / 3.0)
    assert order["target_quantity"] == 2
    assert order["lot_size"] == 2
    assert order["lot_rounding_quantity"] == pytest.approx(4.0 / 3.0)
    assert result.position_quantity(dates[0], "A") == 2


def test_target_lot_rounding_tolerates_binary_float_below_exact_boundary(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=1)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(5.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        lot_size=pd.Series({"A": 10}),
    )
    target = pd.DataFrame(
        np.nextafter(0.5, 0.0), index=dates, columns=["A"]
    )

    result = backend_harness.run_weight_targets(scenario, target)
    order = result.orders(dates[0]).iloc[-1]
    fill = result.fills(dates[0]).iloc[-1]

    assert order["raw_target_quantity"] < 100.0
    assert order["raw_target_quantity"] == pytest.approx(100.0)
    assert order["target_quantity"] == 100
    assert fill["filled_quantity"] == 100
    assert fill["quantity_after_lot"] == 100


def test_target_policy_rejects_unknown_physical_instruments(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=1)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )

    def policy(_date, _feedback):
        return pd.Series({"A": 0.5, "UNKNOWN": 0.1})

    with pytest.raises(ValueError, match="unknown.*UNKNOWN|physical instruments"):
        backend_harness.run_target_policy_probe(scenario, policy)


@pytest.mark.parametrize(
    ("field", "reason_code"),
    [
        ("suspended", "suspended"),
        ("upper_price_limit", "upper_price_limit"),
    ],
)
def test_krx_buy_blocks_preserve_specific_policy_reason(
    backend_harness, field: str, reason_code: str
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=1)
    kwargs = {
        field: pd.DataFrame(True, index=dates, columns=["A"]),
    }
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        **kwargs,
    )

    result = backend_harness.run_weight_targets(
        scenario, pd.DataFrame(1.0, index=dates, columns=["A"])
    )
    fill = result.fills(dates[0]).iloc[-1]

    assert fill["filled_quantity"] == 0
    assert fill["reason_code"] == reason_code
    assert fill["blocked_by"] == "tradability"


def test_krx_lower_price_limit_blocks_sell_with_specific_reason(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        lower_price_limit=pd.DataFrame(
            {"A": [False, True]}, index=dates
        ),
    )
    targets = pd.DataFrame({"A": [1.0, 0.0]}, index=dates)

    result = backend_harness.run_weight_targets(scenario, targets)
    fill = result.fills(dates[1]).iloc[-1]

    assert result.position_quantity(dates[1], "A") == 10
    assert fill["filled_quantity"] == 0
    assert fill["reason_code"] == "lower_price_limit"
    assert fill["blocked_by"] == "tradability"


def test_qlib_zero_fill_after_sell_cash_check_is_not_reported_as_filled(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        cost_policy={
            "stock": {"buy_rate": 0.0, "sell_rate": 2.0, "sell_tax": 0.0}
        },
    )
    targets = pd.DataFrame({"A": [1.0, 0.0]}, index=dates)

    result = backend_harness.run_weight_targets(scenario, targets)
    fill = result.fills(dates[1]).iloc[-1]

    assert fill["filled_quantity"] == 0
    assert fill["quantity_after_position"] == 10
    assert fill["quantity_after_cash"] == 0
    assert fill["quantity_after_lot"] == 0
    assert fill["reason_code"] == "cash_limited"
    assert fill["blocked_by"] == "cash"


def test_krx_asset_class_policy_is_recorded_on_actual_fills(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=1)
    instruments = ["A", "K200_ETF"]
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=instruments),
        universe=pd.DataFrame(True, index=dates, columns=instruments),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(
            1.0, index=dates, columns=instruments
        ),
        asset_class=pd.Series({"A": "stock", "K200_ETF": "etf"}),
        cost_policy={
            "stock": {"buy_rate": 0.001, "sell_rate": 0.0, "sell_tax": 0.002},
            "etf": {"buy_rate": 0.0005, "sell_rate": 0.0, "sell_tax": 0.0},
        },
    )
    targets = pd.DataFrame([[0.5, 0.5]], index=dates, columns=instruments)

    fills = backend_harness.run_weight_targets(scenario, targets).fills()
    by_asset = fills.set_index("asset_class")

    assert by_asset.loc["stock", "execution_policy"] == "krx_stock_v1"
    assert by_asset.loc["etf", "execution_policy"] == "krx_etf_v1"
    assert by_asset.loc["stock", "effective_cost_rate"] == pytest.approx(0.001)
    assert by_asset.loc["etf", "effective_cost_rate"] == pytest.approx(0.0005)
