from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib
import numpy as np
import pandas as pd


INTEGRATION_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = INTEGRATION_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(INTEGRATION_ROOT))

from kwam_enhanced_index.backtest.cost import TradeCostConfig
from kwam_enhanced_index.backtest.holdings import (
    HoldingsLedgerState,
    execute_holdings_ledger_step,
    initialize_holdings_ledger,
)
from kwam_enhanced_index.config import load_config
from kwam_enhanced_index.data.loader import ConfigDrivenDataLoader
from kwam_enhanced_index.orchestration.runs_closed_loop import (
    run_closed_loop_signal_strategy,
)
from kwam_enhanced_index.orchestration.strategy_factory.specs import (
    RAW_PEER_SIGNAL_DIAGNOSTIC_KEY,
    StrategyOutputSpec,
)
from kwam_enhanced_index.portfolio.scale import SideExposureScaler
from kwam_enhanced_index.strategies.peer_momentum import (
    SignalDecayPeerMomentumSignalStrategy,
)
from kwam_enhanced_index.strategies.policies.weighting import (
    ScaledSignalWeightPolicy,
)
from peer_momentum_runtime.data import QlibPeerMomentumData
from qlib_extended import open_run_catalog
from run_signed_peer_momentum import run_signed_peer_momentum


ACTIVE_BOOKSIZE = 1_000_000_000.0
LONG_EXPOSURE = 0.25
SHORT_EXPOSURE = 0.25
MAX_ABS_WEIGHT = 0.05
TOP_FRACTION = 0.05
DECAY_WINDOW = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare production closed-loop and matched-capitalization Qlib PnL."
    )
    parser.add_argument("--start-date", default="2025-01-02")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument(
        "--qlib-output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "outputs" / "signed_peer_momentum",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "outputs" / "signed_peer_momentum_twin",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = compare_signed_peer_momentum(
        start_date=args.start_date,
        end_date=args.end_date,
        qlib_output_dir=args.qlib_output_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def compare_signed_peer_momentum(
    *,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    qlib_output_dir: Path,
    output_dir: Path,
) -> Mapping[str, Any]:
    qlib_dir = qlib_output_dir.resolve()
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    qlib_summary = run_signed_peer_momentum(
        start_date=start_date,
        end_date=end_date,
        output_dir=qlib_dir,
    )
    if float(qlib_summary["execution_cost"]) != 0.0:
        raise ValueError("Qlib twin must run with zero execution cost")

    project = load_config()
    data = QlibPeerMomentumData.from_project_config(
        project,
        etf_ticker="A069500",
        peer_group_dataset="industry_code",
    )
    resolved_start = pd.Timestamp(qlib_summary["start_date"])
    resolved_end = pd.Timestamp(qlib_summary["end_date"])
    dates = data.calendar[
        (data.calendar >= resolved_start) & (data.calendar <= resolved_end)
    ]
    stocks = data.stock_columns
    catalog = open_run_catalog(qlib_dir / "runs.duckdb")
    backtest_run_id = str(qlib_summary["backtest_run_id"])
    project_data = qlib_dir / "project-data"
    realized_return = _load_matrix(project_data / "returns.parquet", "return", dates, stocks)
    peer_groups = _load_matrix(
        project_data / "peer_groups.parquet", "peer_group", dates, stocks
    )
    universe = _align(catalog.load_table(backtest_run_id, "universe"), dates, stocks).astype(
        bool
    )
    base_price = _align(
        catalog.load_table(backtest_run_id, "execution_price"), dates, stocks
    )
    close_price = _align(
        catalog.load_table(backtest_run_id, "valuation_price"), dates, stocks
    )
    loader = ConfigDrivenDataLoader.from_project_config(project)
    adjustment = loader.load_matrix("quantity_adjustment_factor").reindex(
        index=dates, columns=stocks
    )

    strategy = SignalDecayPeerMomentumSignalStrategy(
        name="peer_momentum.ew_decay.top_kpct.long_short.twin",
        peer_group_key="industry_code",
        top_fraction=None,
        decay_window=DECAY_WINDOW,
        decay_dense=False,
        weight_policy=ScaledSignalWeightPolicy(
            scaler=SideExposureScaler(
                long_exposure=LONG_EXPOSURE,
                short_exposure=SHORT_EXPOSURE,
                max_abs_weight=MAX_ABS_WEIGHT,
            ),
            top_fraction=TOP_FRACTION,
        ),
    )
    spec = StrategyOutputSpec(
        key=strategy.name,
        strategy=strategy,
        transform="top_kpct",
        method="ew_decay",
        output_lag=1,
        k=TOP_FRACTION,
        raw_signal_diagnostic_key=RAW_PEER_SIGNAL_DIAGNOSTIC_KEY,
    )
    production = run_closed_loop_signal_strategy(
        spec=spec,
        strategy_matrices={"returns": realized_return, "industry_code": peer_groups},
        universe_mask=universe,
        realized_return=realized_return,
        execution_base_price=base_price,
        execution_close_price=close_price,
        quantity_adjustment_factor=adjustment,
        trade_cost_config=TradeCostConfig(enabled=False),
    )

    production_pnl = _production_pnl(
        production.held_quantity,
        production.nav,
        base_price,
        close_price,
    )
    qlib_pnl = pd.read_parquet(qlib_dir / "pnl-attribution.parquet")
    qlib_pnl["trade_date"] = pd.to_datetime(qlib_pnl["trade_date"])
    comparison = production_pnl.merge(
        qlib_pnl[
            ["trade_date", "long_pnl", "short_pnl", "total_pnl"]
        ].rename(
            columns={
                "long_pnl": "qlib_long_pnl",
                "short_pnl": "qlib_short_pnl",
                "total_pnl": "qlib_total_pnl",
            }
        ),
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    for leg in ("long", "short", "total"):
        comparison[f"{leg}_pnl_difference"] = (
            comparison[f"production_{leg}_pnl"] - comparison[f"qlib_{leg}_pnl"]
        )

    signed = catalog.load_table(backtest_run_id, "signed_positions")
    qlib_intended = signed.pivot(
        index="trade_date", columns="instrument_id", values="intended_weight"
    ).reindex(index=dates, columns=stocks)
    production_applied = production.applied_weight.reindex(index=dates, columns=stocks)
    intended_difference = production_applied - qlib_intended
    first_weight_divergence = _first_matrix_divergence(intended_difference)
    fractional_quantities, fractional_nav = _run_fractional_target_ledger(
        target_weights=qlib_intended,
        universe=universe,
        realized_return=realized_return,
        base_price=base_price,
        close_price=close_price,
        adjustment=adjustment,
    )
    fractional_pnl = _production_pnl(
        fractional_quantities,
        fractional_nav,
        base_price,
        close_price,
    ).rename(columns=lambda name: name.replace("production_", "fractional_"))
    comparison = comparison.merge(
        fractional_pnl[
            [
                "trade_date",
                "fractional_long_pnl",
                "fractional_short_pnl",
                "fractional_total_pnl",
            ]
        ],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    )
    for leg in ("long", "short", "total"):
        comparison[f"selection_{leg}_pnl_difference"] = (
            comparison[f"production_{leg}_pnl"]
            - comparison[f"fractional_{leg}_pnl"]
        )
        comparison[f"execution_{leg}_pnl_difference"] = (
            comparison[f"fractional_{leg}_pnl"] - comparison[f"qlib_{leg}_pnl"]
        )

    production_pnl.to_parquet(destination / "production-pnl-attribution.parquet", index=False)
    fractional_pnl.to_parquet(
        destination / "fractional-qlib-intent-pnl-attribution.parquet", index=False
    )
    comparison.to_parquet(destination / "daily-pnl-comparison.parquet", index=False)
    production.desired_target_active_weight.to_parquet(
        destination / "production-desired-weights.parquet"
    )
    production_applied.to_parquet(destination / "production-applied-weights.parquet")
    qlib_intended.to_parquet(destination / "qlib-intended-weights.parquet")
    intended_difference.to_parquet(destination / "intended-weight-difference.parquet")
    figure_path = destination / "production-vs-qlib-pnl.png"
    _plot_comparison(comparison, figure_path)

    production_totals = {
        leg: float(production_pnl[f"production_{leg}_pnl"].sum())
        for leg in ("long", "short", "total")
    }
    qlib_totals = {
        leg: float(comparison[f"qlib_{leg}_pnl"].sum())
        for leg in ("long", "short", "total")
    }
    total_difference = production_totals["total"] - qlib_totals["total"]
    fractional_totals = {
        leg: float(comparison[f"fractional_{leg}_pnl"].sum())
        for leg in ("long", "short", "total")
    }
    selection_difference = (
        production_totals["total"] - fractional_totals["total"]
    )
    execution_difference = fractional_totals["total"] - qlib_totals["total"]
    summary = {
        "start_date": resolved_start,
        "end_date": resolved_end,
        "trading_days": len(comparison),
        "conditions": {
            "cost": 0.0,
            "long_exposure": LONG_EXPOSURE,
            "short_exposure": SHORT_EXPOSURE,
            "max_abs_weight": MAX_ABS_WEIGHT,
            "top_fraction": TOP_FRACTION,
            "decay_window": DECAY_WINDOW,
            "execution": "same-day base price",
            "valuation": "same-day close price",
            "active_booksize": ACTIVE_BOOKSIZE,
        },
        "production_pnl": production_totals,
        "fractional_qlib_intent_pnl": fractional_totals,
        "qlib_pnl": qlib_totals,
        "production_minus_qlib_total_pnl": total_difference,
        "total_pnl_difference_bps": total_difference / ACTIVE_BOOKSIZE * 10_000.0,
        "selection_semantics_total_pnl_difference": selection_difference,
        "selection_semantics_difference_bps": (
            selection_difference / ACTIVE_BOOKSIZE * 10_000.0
        ),
        "qlib_execution_total_pnl_difference": execution_difference,
        "qlib_execution_difference_bps": (
            execution_difference / ACTIVE_BOOKSIZE * 10_000.0
        ),
        "max_abs_daily_total_pnl_difference": float(
            comparison["total_pnl_difference"].abs().max()
        ),
        "max_abs_cumulative_total_pnl_difference": float(
            comparison["total_pnl_difference"].cumsum().abs().max()
        ),
        "daily_total_pnl_correlation": float(
            comparison["production_total_pnl"].corr(
                comparison["qlib_total_pnl"]
            )
        ),
        "daily_total_pnl_sign_agreement": float(
            (
                np.sign(comparison["production_total_pnl"])
                == np.sign(comparison["qlib_total_pnl"])
            ).mean()
        ),
        "max_abs_intended_weight_difference": float(
            intended_difference.abs().max().max()
        ),
        "first_intended_weight_divergence": first_weight_divergence,
        "production_pnl_reconciliation_max_abs_error": float(
            production_pnl["production_reconciliation_error"].abs().max()
        ),
        "qlib_pnl_reconciliation_max_abs_error": float(
            qlib_summary["max_pnl_attribution_error"]
        ),
        "qlib_backtest_run_id": backtest_run_id,
        "figure": str(figure_path),
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


def _align(
    matrix: pd.DataFrame, dates: pd.DatetimeIndex, stocks: pd.Index
) -> pd.DataFrame:
    normalized = matrix.copy()
    normalized.index = pd.DatetimeIndex(normalized.index)
    normalized.columns = normalized.columns.astype(str)
    return normalized.reindex(index=dates, columns=stocks)


def _load_matrix(
    path: Path,
    value_column: str,
    dates: pd.DatetimeIndex,
    stocks: pd.Index,
) -> pd.DataFrame:
    table = pd.read_parquet(path)
    table["date"] = pd.to_datetime(table["date"])
    matrix = table.pivot(index="date", columns="ticker", values=value_column)
    return matrix.reindex(index=dates, columns=stocks)


def _production_pnl(
    held_quantity: pd.DataFrame,
    nav: pd.Series,
    base_price: pd.DataFrame,
    close_price: pd.DataFrame,
) -> pd.DataFrame:
    contribution = held_quantity * (close_price - base_price) * ACTIVE_BOOKSIZE
    long_pnl = contribution.where(held_quantity.gt(0.0), 0.0).sum(axis=1)
    short_pnl = contribution.where(held_quantity.lt(0.0), 0.0).sum(axis=1)
    total_pnl = long_pnl + short_pnl
    prior_nav = nav.shift(1, fill_value=1.0)
    account_pnl = (nav - prior_nav) * ACTIVE_BOOKSIZE
    return pd.DataFrame(
        {
            "trade_date": held_quantity.index,
            "production_long_pnl": long_pnl.to_numpy(),
            "production_short_pnl": short_pnl.to_numpy(),
            "production_total_pnl": total_pnl.to_numpy(),
            "production_account_pnl": account_pnl.to_numpy(),
            "production_reconciliation_error": (total_pnl - account_pnl).to_numpy(),
        }
    )


def _run_fractional_target_ledger(
    *,
    target_weights: pd.DataFrame,
    universe: pd.DataFrame,
    realized_return: pd.DataFrame,
    base_price: pd.DataFrame,
    close_price: pd.DataFrame,
    adjustment: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series]:
    state = initialize_holdings_ledger(target_weights.columns)
    quantities = pd.DataFrame(
        0.0, index=target_weights.index, columns=target_weights.columns
    )
    nav = pd.Series(0.0, index=target_weights.index, dtype="float64")
    execution_universe = universe & realized_return.notna()
    for trade_date in target_weights.index:
        step = execute_holdings_ledger_step(
            decision_date=pd.Timestamp(trade_date),
            state=state,
            target_weight=target_weights.loc[trade_date],
            base_price=base_price.loc[trade_date],
            close_price=close_price.loc[trade_date],
            quantity_adjustment_factor=adjustment.loc[trade_date],
            execution_universe_mask=execution_universe.loc[trade_date],
            rebalance=True,
            trade_cost_config=TradeCostConfig(enabled=False),
        )
        quantities.loc[trade_date] = step.closing_quantity
        nav.loc[trade_date] = step.nav
        state = HoldingsLedgerState(
            quantity=step.closing_quantity.copy(),
            cash=step.cash,
            nav=step.nav,
        )
    return quantities, nav


def _first_matrix_divergence(matrix: pd.DataFrame) -> Mapping[str, Any] | None:
    stacked = matrix.abs().stack(future_stack=True)
    divergent = stacked[stacked > 1e-12]
    if divergent.empty:
        return None
    date, ticker = divergent.index[0]
    return {
        "trade_date": pd.Timestamp(date),
        "ticker": str(ticker),
        "difference": float(matrix.loc[date, ticker]),
    }


def _plot_comparison(comparison: pd.DataFrame, output_path: Path) -> None:
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    dates = pd.to_datetime(comparison["trade_date"])
    colors = {"long": "#0068B5", "short": "#D1495B", "total": "#2A9D8F"}
    figure, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=True)
    for leg in ("long", "short", "total"):
        axes[0].plot(
            dates,
            comparison[f"production_{leg}_pnl"].cumsum(),
            color=colors[leg],
            linewidth=2.0,
            label=f"Production {leg.title()}",
        )
        axes[0].plot(
            dates,
            comparison[f"qlib_{leg}_pnl"].cumsum(),
            color=colors[leg],
            linewidth=1.3,
            linestyle="--",
            label=f"Qlib {leg.title()}",
        )
        axes[1].plot(
            dates,
            comparison[f"{leg}_pnl_difference"].cumsum(),
            color=colors[leg],
            linewidth=1.8,
            label=leg.title(),
        )
    axes[0].set_title("Production Closed Loop vs Qlib — Cumulative PnL")
    axes[0].set_ylabel("Cumulative PnL (KRW)")
    axes[0].legend(ncol=2)
    axes[1].set_title("Cumulative Difference — Production minus Qlib")
    axes[1].set_ylabel("PnL difference (KRW)")
    axes[1].set_xlabel("Trade date")
    axes[1].legend(ncol=3)
    for axis in axes:
        axis.axhline(0.0, color="#59636E", linewidth=0.8)
        axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    main()
