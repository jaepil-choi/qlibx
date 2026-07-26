from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    if str(INTEGRATION_ROOT) not in sys.path:
        sys.path.insert(0, str(INTEGRATION_ROOT))
    path = INTEGRATION_ROOT / "research" / "report" / "build_report_assets.py"
    spec = importlib.util.spec_from_file_location("report_asset_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load report builder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_order_blotter_uses_integer_quantity_book_and_reconciles_cash(
    tmp_path: Path,
) -> None:
    builder = load_builder()
    previous_date = pd.Timestamp("2026-01-02")
    trade_date = pd.Timestamp("2026-01-05")
    physical = pd.DataFrame(
        {
            "A000001": [0.30, 0.20],
            "A000002": [0.20, 0.30],
            "A069500": [0.50, 0.50],
        },
        index=[previous_date, trade_date],
    )
    price_path = tmp_path / "adjusted_prices.parquet"
    pd.DataFrame(
        [
            {
                "date": date,
                "ticker": ticker,
                "기준가": price,
            }
            for date, prices in (
                (previous_date, (100.0, 200.0, 1_000.0)),
                (trade_date, (110.0, 190.0, 1_010.0)),
            )
            for ticker, price in zip(
                ("A000001", "A000002", "A069500"),
                prices,
                strict=True,
            )
        ]
    ).to_parquet(price_path, index=False)
    member_path = tmp_path / "k200_members.parquet"
    pd.DataFrame(
        {
            "date": [trade_date, trade_date],
            "ticker": ["A000001", "A000002"],
            "ticker_name": ["종목1", "종목2"],
            "index_weight": [0.60, 0.40],
        }
    ).to_parquet(member_path, index=False)

    builder.ADJUSTED_PRICES = price_path
    builder.K200_MEMBERS = member_path
    builder.SAMPLE_INITIAL_NAV = 1_000_000.0

    blotter = builder.build_quantity_order_blotter(physical)

    assert {
        "fund_code",
        "base_date",
        "ticker",
        "ticker_name",
        "current_quantity",
        "target_quantity",
        "side",
        "order_quantity",
        "reference_price",
        "expected_order_amount",
        "estimated_trade_cost",
        "pre_trade_weight",
        "post_trade_weight",
        "benchmark_weight",
        "post_active_weight",
        "residual_cash",
        "constraint_result",
        "constraint_details",
    }.issubset(blotter.columns)
    assert blotter["order_quantity"].gt(0).all()
    assert blotter["current_quantity"].mod(1).eq(0).all()
    assert blotter["target_quantity"].mod(1).eq(0).all()
    assert set(blotter["side"]).issubset({"BUY", "SELL"})
    assert blotter["residual_cash"].ge(0.0).all()
    assert blotter["constraint_result"].eq("PASS").all()
    assert (
        blotter["constraint_details"]
        .str.contains(
            "account_reconciled=PASS",
            regex=False,
        )
        .all()
    )


def test_transfer_coefficient_excludes_inactive_source_dates() -> None:
    builder = load_builder()
    index = pd.date_range("2026-01-02", periods=4, freq="B")
    source = pd.Series([0.0, 0.01, -0.01, 0.02], index=index)
    physical = pd.Series([1.0, 0.02, -0.02, 0.04], index=index)

    coefficient = builder.transfer_coefficient(source, physical)

    assert coefficient == pytest.approx(1.0)
    assert len(builder.transfer_sample(source, physical)) == 3


def test_neutralization_diagnostic_compares_open_close_baseline_with_market_demean(
    tmp_path: Path,
) -> None:
    builder = load_builder()
    index = pd.bdate_range("2026-01-02", periods=3)
    columns = pd.Index(["A", "B", "C"])
    weight_path = tmp_path / "open_close_rebound.parquet"
    universe_path = tmp_path / "universe_mask.parquet"
    benchmark_path = tmp_path / "benchmark_weight.parquet"
    pd.DataFrame(
        [[1.0, 0.0, 0.0]] * len(index),
        index=index,
        columns=columns,
    ).to_parquet(weight_path)
    pd.DataFrame(True, index=index, columns=columns).to_parquet(universe_path)
    pd.DataFrame(
        [[0.5, 0.3, 0.2]] * len(index),
        index=index,
        columns=columns,
    ).to_parquet(benchmark_path)

    class StubLoader:
        @classmethod
        def from_directory(cls, _path: Path):
            return cls()

        def load_matrix(self, name: str) -> pd.DataFrame:
            assert name == "adjusted_return"
            return pd.DataFrame(
                [[0.01, 0.0, 0.0]] * len(index),
                index=index,
                columns=columns,
            )

    builder.OPEN_CLOSE_REBOUND_WEIGHT = weight_path
    builder.OPEN_CLOSE_REBOUND_UNIVERSE = universe_path
    builder.OPEN_CLOSE_REBOUND_BENCHMARK_WEIGHT = benchmark_path
    builder.ConfigDrivenDataLoader = StubLoader

    diagnostic = builder.build_neutralization_diagnostic(index)

    assert list(diagnostic.columns) == [
        "baseline_return",
        "market_demeaned_return",
        "baseline_beta",
        "market_demeaned_beta",
    ]
    assert diagnostic["baseline_return"].eq(0.01).all()
    assert diagnostic["market_demeaned_return"].eq(0.005).all()


def test_market_demean_preserves_daily_gross_and_removes_net_exposure() -> None:
    builder = load_builder()
    index = pd.bdate_range("2026-01-02", periods=2)
    columns = pd.Index(["A", "B", "C"])
    baseline = pd.DataFrame(
        [[1.0, 0.0, 0.0], [0.6, 0.2, 0.0]],
        index=index,
        columns=columns,
    )
    universe = pd.DataFrame(True, index=index, columns=columns)

    demeaned = builder.market_demean_preserving_gross(baseline, universe)

    pd.testing.assert_series_equal(
        demeaned.abs().sum(axis=1),
        baseline.abs().sum(axis=1),
    )
    assert demeaned.sum(axis=1).abs().max() <= 1e-12
