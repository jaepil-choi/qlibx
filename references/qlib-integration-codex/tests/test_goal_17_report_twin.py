from __future__ import annotations

from pathlib import Path

import pandas as pd

from qlib_extended.config import BacktestConfig
from qlib_extended.execution import ExecutionContext, run_qlib_backtest
from qlib_extended.research.reporting import (
    REPORT_SELECTION_KEY,
    validate_systematic_report_bundle,
)


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = INTEGRATION_ROOT.parent


def test_report_bundle_reproduces_dynamic_shadow_selection_daily_kpis() -> None:
    proof = validate_systematic_report_bundle(PROJECT_ROOT)

    assert proof["status"] == "PASS"
    assert proof["final_method_key"] == REPORT_SELECTION_KEY
    assert proof["figure_count"] == 11
    assert proof["table_count"] == 4
    assert proof["max_kpi_error"] <= 1e-12
    assert proof["financial_pit_verified"] is False
    assert proof["true_forward_oos"] is False


def test_target_weight_executes_stock_and_etf_contract_in_qlib() -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    columns = pd.Index(["A", "B", "K200_ETF"], name="instrument_id")
    target = pd.DataFrame(
        [[0.60, 0.10, 0.30], [0.20, 0.30, 0.50]],
        index=dates,
        columns=columns,
    )
    price = pd.DataFrame(100.0, index=dates, columns=columns)
    universe = pd.DataFrame(True, index=dates, columns=columns)
    benchmark = pd.DataFrame(0.0, index=dates, columns=columns)

    output = run_qlib_backtest(
        target,
        BacktestConfig(
            initial_cash=1_000_000.0,
            execution_price="execution_price",
            universe="universe",
            benchmark_weight="benchmark_weight",
            signal_lag=0,
            target_semantics="target_weight",
            cost_policy={
                "stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0},
                "etf": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0},
            },
        ),
        ExecutionContext(
            execution_price=price,
            universe=universe,
            benchmark_weight=benchmark,
            asset_class=pd.Series(
                {"A": "stock", "B": "stock", "K200_ETF": "etf"}
            ),
            lot_size=pd.Series(1, index=columns, dtype="int64"),
        ),
    )

    pd.testing.assert_frame_equal(output.artifacts["target_weights"], target)
    instrument = output.artifacts["instrument_contract"]
    assert instrument.loc["K200_ETF", "asset_class"] == "etf"
    assert instrument.loc["K200_ETF", "lot_size"] == 1
    assert output.metadata["execution_backend"] == "qlib"
    assert REPORT_SELECTION_KEY.endswith(
        "minimum_variance_momentum__family_breadth_conviction"
    )
