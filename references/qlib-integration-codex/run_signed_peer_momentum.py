from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import matplotlib
import pandas as pd
import yaml


INTEGRATION_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = INTEGRATION_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(INTEGRATION_ROOT))

from kwam_enhanced_index.config import load_config
from kwam_enhanced_index.data.loader import ConfigDrivenDataLoader
from peer_momentum_runtime.data import QlibPeerMomentumData
from qlib_extended import create_report, open_run_catalog, run_strategy_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest signed peer momentum through matched capitalization."
    )
    parser.add_argument("--start-date", default="2025-01-02")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "outputs" / "signed_peer_momentum",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_signed_peer_momentum(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def run_signed_peer_momentum(
    *,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    output_dir: Path,
) -> Mapping[str, Any]:
    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    project = load_config()
    data = QlibPeerMomentumData.from_project_config(
        project,
        etf_ticker="A069500",
        peer_group_dataset="industry_code",
    )
    resolved_start, resolved_end = data.resolve_run_dates(start_date, end_date)
    dates = data.calendar[
        (data.calendar >= resolved_start) & (data.calendar <= resolved_end)
    ]
    stocks = data.stock_columns
    loader = ConfigDrivenDataLoader.from_project_config(project)
    raw_execution_price = loader.load_matrix("execution_base_price").reindex(
        index=dates, columns=stocks
    )
    raw_valuation_price = data.execution_price.loc[dates, stocks]
    raw_volume = data.volume.loc[dates, stocks]
    price_valid = (
        raw_execution_price.notna()
        & raw_execution_price.gt(0.0)
        & raw_valuation_price.notna()
        & raw_valuation_price.gt(0.0)
    )
    volume_valid = raw_volume.notna() & raw_volume.ge(0.0)
    observed = price_valid & volume_valid
    tradable = observed & ~data.suspended.loc[dates, stocks]
    universe = data.universe_mask.loc[dates, stocks] & observed
    shortable = universe & tradable

    matrices = {
        "returns": data.returns.loc[dates, stocks],
        "peer_groups": data.peer_groups.loc[dates, stocks],
        "universe": universe.astype(bool),
        "observed": observed.astype(bool),
        "tradable": tradable.astype(bool),
        "shortable": shortable.astype(bool),
        "execution_price": raw_execution_price.ffill().fillna(1.0).astype(
            "float64"
        ),
        "valuation_price": raw_valuation_price.ffill().fillna(1.0).astype(
            "float64"
        ),
        "volume": raw_volume.fillna(0.0).astype("float64"),
        "benchmark_weight": pd.DataFrame(0.0, index=dates, columns=stocks),
    }
    data_dir = destination / "project-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    value_columns = {
        "returns": "return",
        "peer_groups": "peer_group",
        "universe": "in_universe",
        "observed": "observed",
        "tradable": "tradable",
        "shortable": "shortable",
        "execution_price": "execution_price",
        "valuation_price": "valuation_price",
        "volume": "volume",
        "benchmark_weight": "benchmark_weight",
    }
    datasets: dict[str, dict[str, str]] = {}
    for name, matrix in matrices.items():
        path = data_dir / f"{name}.parquet"
        _write_matrix(path, matrix, value_columns[name])
        datasets[name] = {
            "path": str(path),
            "format": "parquet",
            "value_column": value_columns[name],
        }

    composite_cash = 3_000_000_000.0
    active_booksize = 1_000_000_000.0
    config = {
        "version": 1,
        "run_store": {
            "catalog_uri": str(destination / "runs.duckdb"),
            "artifact_dir": str(destination / "artifacts"),
        },
        "data": {"datasets": datasets},
        "backtest": {
            "initial_cash": composite_cash,
            "execution_price": "execution_price",
            "valuation_price": "valuation_price",
            "universe": "universe",
            "benchmark_weight": "benchmark_weight",
            "signal_lag": 0,
            "target_semantics": "signed_weight",
            "matched_capitalization": {
                "observed": "observed",
                "tradable": "tradable",
                "shortable": "shortable",
                "per_name_short_cap": 0.06,
                "safety_multiplier": 1.10,
                "inventory_readiness": "same_bar",
                "inventory_retention": "active_short_only",
                "active_booksize": active_booksize,
            },
            "execution": {
                "volume": "volume",
                "max_volume_participation": 0.10,
            },
            "cost_policy": {
                "stock": {
                    "buy_rate": 0.0,
                    "sell_rate": 0.0,
                    "sell_tax": 0.0,
                }
            },
        },
        "strategies": {
            "peer_momentum.ew_decay.top_kpct.long_short": {
                "callable": (
                    "peer_momentum_runtime.signed_alpha:"
                    "build_signed_peer_momentum_alpha"
                ),
                "datasets": {
                    "returns": "returns",
                    "peer_groups": "peer_groups",
                    "universe": "universe",
                },
                "parameters": {
                    "decay_window": 5,
                    "decay_dense": False,
                    "top_fraction": 0.05,
                    "long_exposure": 0.25,
                    "short_exposure": 0.25,
                    "max_abs_weight": 0.05,
                },
            }
        },
    }
    config_path = destination / "project.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    strategy_id = "peer_momentum.ew_decay.top_kpct.long_short"
    outcome = run_strategy_batch(
        config_path,
        strategy_ids=(strategy_id,),
        max_workers=1,
    )
    run = outcome.runs[0]
    catalog = open_run_catalog(destination / "runs.duckdb")
    active = catalog.load_table(run.backtest_run_id, "active_account_daily")
    baseline = catalog.load_table(run.backtest_run_id, "baseline_account_daily")
    composite = catalog.load_table(run.backtest_run_id, "account_daily")
    signed = catalog.load_table(run.backtest_run_id, "signed_positions")
    orders = catalog.load_table(run.backtest_run_id, "orders")
    fills = catalog.load_table(run.backtest_run_id, "fills")
    alpha = catalog.load_alpha(run.alpha_run_id)
    pnl_attribution = _build_pnl_attribution(
        signed=signed,
        active_account=active,
        execution_price=catalog.load_table(
            run.backtest_run_id, "execution_price"
        ),
        valuation_price=catalog.load_table(
            run.backtest_run_id, "valuation_price"
        ),
    )
    pnl_attribution.to_parquet(
        destination / "pnl-attribution.parquet", index=False
    )
    report = create_report(
        destination / "runs.duckdb",
        backtest_run_ids=(run.backtest_run_id,),
        output_dir=destination / "report",
        include_png=True,
    )
    pnl_path = destination / "peer-momentum-long-short-pnl.png"
    _plot_pnl(pnl_attribution, pnl_path)
    summary = {
        "strategy_id": strategy_id,
        "start_date": resolved_start,
        "end_date": resolved_end,
        "alpha_run_id": run.alpha_run_id,
        "backtest_run_id": run.backtest_run_id,
        "trading_days": len(active),
        "final_active_nav": float(active.iloc[-1]["nav"]),
        "active_money_pnl": float(active.iloc[-1]["nav"] - active_booksize),
        "active_total_return": float(
            active["portfolio_return"].astype("float64").sum()
        ),
        "long_money_pnl": float(pnl_attribution["long_pnl"].sum()),
        "short_money_pnl": float(pnl_attribution["short_pnl"].sum()),
        "attributed_total_money_pnl": float(
            pnl_attribution["total_pnl"].sum()
        ),
        "execution_cost": float(fills["trade_cost"].sum()),
        "average_long_exposure": float(alpha.clip(lower=0.0).sum(axis=1).mean()),
        "average_short_exposure": float(
            -alpha.clip(upper=0.0).sum(axis=1).mean()
        ),
        "order_count": len(orders),
        "filled_order_count": int(fills["filled_quantity"].gt(0).sum()),
        "max_nav_reconciliation_error": float(
            (
                composite.set_index("trade_date")["nav"]
                - baseline.set_index("trade_date")["nav"]
                - active.set_index("trade_date")["nav"]
            )
            .abs()
            .max()
        ),
        "max_composite_position_shortfall": float(
            signed["composite_quantity"].clip(upper=0.0).abs().max()
        ),
        "max_pnl_attribution_error": float(
            pnl_attribution["reconciliation_error"].abs().max()
        ),
        "report_html": str(report.html_path),
        "pnl_figure": str(pnl_path),
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


def _write_matrix(path: Path, matrix: pd.DataFrame, value_name: str) -> None:
    named = matrix.copy().rename_axis(index="date", columns="ticker")
    (
        named.stack(future_stack=True)
        .rename(value_name)
        .reset_index()
        .to_parquet(path, index=False)
    )


def _build_pnl_attribution(
    *,
    signed: pd.DataFrame,
    active_account: pd.DataFrame,
    execution_price: pd.DataFrame,
    valuation_price: pd.DataFrame,
) -> pd.DataFrame:
    held = signed.pivot(
        index="trade_date",
        columns="instrument_id",
        values="held_quantity",
    ).reindex(index=execution_price.index, columns=execution_price.columns)
    intraday_move = valuation_price - execution_price
    contribution = held.astype("float64") * intraday_move.astype("float64")
    long_pnl = contribution.where(held.gt(0.0), 0.0).sum(axis=1)
    short_pnl = contribution.where(held.lt(0.0), 0.0).sum(axis=1)
    total_pnl = long_pnl + short_pnl
    active_money_pnl = active_account.set_index("trade_date")["money_pnl"].reindex(
        execution_price.index
    )
    result = pd.DataFrame(
        {
            "trade_date": execution_price.index,
            "long_pnl": long_pnl.to_numpy(),
            "short_pnl": short_pnl.to_numpy(),
            "total_pnl": total_pnl.to_numpy(),
            "active_money_pnl": active_money_pnl.to_numpy(),
        }
    )
    result["reconciliation_error"] = (
        result["total_pnl"] - result["active_money_pnl"]
    )
    return result


def _plot_pnl(pnl: pd.DataFrame, output_path: Path) -> None:
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    pnl = pnl.sort_values("trade_date")
    dates = pd.to_datetime(pnl["trade_date"])
    cumulative = pnl[["long_pnl", "short_pnl", "total_pnl"]].cumsum()
    figure, axis = plt.subplots(figsize=(12, 6.5))
    axis.plot(
        dates,
        cumulative["long_pnl"],
        label="Long PnL",
        color="#0068B5",
        linewidth=1.8,
    )
    axis.plot(
        dates,
        cumulative["short_pnl"],
        label="Short PnL",
        color="#D1495B",
        linewidth=1.8,
    )
    axis.plot(
        dates,
        cumulative["total_pnl"],
        label="Total PnL",
        color="#2A9D8F",
        linewidth=2.3,
    )
    axis.axhline(0.0, color="#59636E", linewidth=0.8)
    axis.set_ylabel("Cumulative PnL (KRW)")
    axis.set_xlabel("Trade date")
    axis.set_title("Peer Momentum Long-Short — Cost 0, Base-to-Close")
    axis.legend(loc="best")
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    main()
