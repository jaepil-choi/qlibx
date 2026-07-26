from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parents[1]
SRC_DIR = PROJECT_ROOT / "src"
for import_root in (str(SRC_DIR), str(THIS_DIR)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

import qlib
from qlib.backtest import backtest
from qlib.backtest.executor import SimulatorExecutor
from qlib.constant import REG_US

from kwam_qlib.data import PeerMomentumInputs, load_peer_momentum_inputs
from kwam_qlib.exchange import DataFrameExchange, build_quote_frame
from kwam_qlib.signals import compute_equal_weight_peer_momentum
from kwam_qlib.strategy import (
    ConsecutiveLossStopPeerMomentumStrategy,
    QlibPeerMomentumStrategy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the KOSPI200 peer-momentum twin through Qlib backtest."
    )
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date")
    parser.add_argument("--active-multiplier", type=float, default=0.10)
    parser.add_argument("--top-fraction", type=float)
    parser.add_argument(
        "--variant",
        choices=("base", "three_day_loss_stop"),
        default="base",
    )
    parser.add_argument("--account", type=float, default=1_000_000_000.0)
    parser.add_argument("--risk-degree", type=float, default=0.999)
    parser.add_argument("--buy-cost", type=float, default=0.0003)
    parser.add_argument("--sell-cost", type=float, default=0.0023)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=THIS_DIR / "outputs" / "peer_momentum_backtest",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = load_peer_momentum_inputs()
    start_date, end_date = _resolve_run_dates(
        inputs.calendar,
        args.start_date,
        args.end_date,
    )
    prediction_start = inputs.calendar[inputs.calendar.get_loc(start_date) - 1]
    signal_dates = inputs.calendar[
        (inputs.calendar >= prediction_start) & (inputs.calendar < end_date)
    ]

    raw_signal = compute_equal_weight_peer_momentum(
        inputs.returns.loc[signal_dates],
        inputs.industry_code.loc[signal_dates],
        inputs.universe_mask.loc[signal_dates],
    )
    signal = _matrix_to_qlib_signal(raw_signal)

    output_dir = args.output_dir.resolve()
    provider_dir = output_dir / "provider"
    _write_minimal_provider(provider_dir, inputs.calendar, inputs.tickers)
    qlib.init(
        provider_uri=str(provider_dir),
        region=REG_US,
        expression_cache=None,
        dataset_cache=None,
    )

    quote_start = prediction_start
    quote_dates = inputs.calendar[
        (inputs.calendar >= quote_start) & (inputs.calendar <= end_date)
    ]
    quote = build_quote_frame(
        inputs.adjusted_close.loc[quote_dates],
        inputs.returns.loc[quote_dates],
        inputs.trade_volume.loc[quote_dates],
    )
    exchange = DataFrameExchange(
        quote_frame=quote,
        freq="day",
        start_time=quote_start,
        end_time=end_date,
        codes=inputs.tickers.tolist(),
        deal_price="close",
        limit_threshold=None,
        open_cost=args.buy_cost,
        close_cost=args.sell_cost,
        min_cost=0.0,
        trade_unit=None,
    )
    strategy_cls = (
        ConsecutiveLossStopPeerMomentumStrategy
        if args.variant == "three_day_loss_stop"
        else QlibPeerMomentumStrategy
    )
    strategy = strategy_cls(
        signal=signal,
        benchmark_weight=inputs.benchmark_weight,
        universe_mask=inputs.universe_mask,
        active_multiplier=args.active_multiplier,
        top_fraction=args.top_fraction,
        risk_degree=args.risk_degree,
    )
    executor = SimulatorExecutor(
        time_per_step="day",
        generate_portfolio_metrics=True,
        verbose=False,
    )
    qlib_benchmark = _benchmark_return(inputs, inputs.calendar)
    portfolio_metrics, indicator_metrics = backtest(
        start_time=start_date,
        end_time=end_date,
        strategy=strategy,
        executor=executor,
        benchmark=qlib_benchmark,
        account=args.account,
        exchange_kwargs={"exchange": exchange},
    )

    report, positions = portfolio_metrics["1day"]
    indicators, _ = indicator_metrics["1day"]
    benchmark_return = _benchmark_return(inputs, report.index)
    targets = pd.DataFrame.from_dict(strategy.target_history, orient="index").reindex(
        columns=inputs.tickers
    )
    active_weights = pd.DataFrame.from_dict(
        strategy.active_history, orient="index"
    ).reindex(columns=inputs.tickers)
    summary = _build_summary(
        report,
        benchmark_return,
        targets,
        raw_signal,
        args,
        start_date,
        end_date,
        strategy,
    )
    feedback_history = pd.DataFrame(
        [vars(item) for item in getattr(strategy, "portfolio_feedback_history", [])]
    )
    if not feedback_history.empty:
        feedback_history = feedback_history.set_index("date")
    _write_outputs(
        output_dir,
        report,
        indicators,
        benchmark_return,
        targets,
        active_weights,
        raw_signal,
        summary,
        positions,
        feedback_history,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _resolve_run_dates(
    calendar: pd.DatetimeIndex,
    start_value: str,
    end_value: str | None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    requested_start = pd.Timestamp(start_value)
    candidates = calendar[calendar >= requested_start]
    if candidates.empty:
        raise ValueError(f"No trading date on or after {requested_start.date()}.")
    start_date = pd.Timestamp(candidates[0])
    if calendar.get_loc(start_date) == 0:
        raise ValueError("Backtest start requires one prior prediction date.")

    requested_end = pd.Timestamp(end_value) if end_value else pd.Timestamp(calendar[-1])
    end_candidates = calendar[calendar <= requested_end]
    if end_candidates.empty:
        raise ValueError(f"No trading date on or before {requested_end.date()}.")
    end_date = pd.Timestamp(end_candidates[-1])
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date.")
    return start_date, end_date


def _matrix_to_qlib_signal(matrix: pd.DataFrame) -> pd.Series:
    named = matrix.copy()
    named.index = named.index.rename("datetime")
    named.columns = named.columns.rename("instrument")
    signal = named.stack(future_stack=True)
    signal.name = "score"
    return signal.sort_index()


def _write_minimal_provider(
    provider_dir: Path,
    calendar: pd.DatetimeIndex,
    tickers: pd.Index,
) -> None:
    calendars_dir = provider_dir / "calendars"
    instruments_dir = provider_dir / "instruments"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    sentinel = pd.Timestamp(calendar[-1]) + pd.offsets.BDay(1)
    calendar_lines = [date.strftime("%Y-%m-%d") for date in calendar]
    calendar_lines.append(sentinel.strftime("%Y-%m-%d"))
    (calendars_dir / "day.txt").write_text(
        "\n".join(calendar_lines) + "\n", encoding="utf-8"
    )
    first = calendar[0].strftime("%Y-%m-%d")
    last = calendar[-1].strftime("%Y-%m-%d")
    instrument_lines = [f"{ticker}\t{first}\t{last}" for ticker in tickers]
    (instruments_dir / "all.txt").write_text(
        "\n".join(instrument_lines) + "\n", encoding="utf-8"
    )


def _benchmark_return(
    inputs: PeerMomentumInputs,
    report_index: pd.DatetimeIndex,
) -> pd.Series:
    weights = inputs.benchmark_weight.fillna(0.0)
    totals = weights.sum(axis=1).replace(0.0, np.nan)
    normalized = weights.div(totals, axis=0)
    benchmark = (normalized.shift(1) * inputs.returns).sum(axis=1, min_count=1)
    return benchmark.reindex(report_index).rename("benchmark_return")


def _build_summary(
    report: pd.DataFrame,
    benchmark_return: pd.Series,
    targets: pd.DataFrame,
    raw_signal: pd.DataFrame,
    args: argparse.Namespace,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    strategy: QlibPeerMomentumStrategy,
) -> dict[str, object]:
    gross = report["return"].astype("float64")
    cost = report["cost"].astype("float64")
    net = gross - cost
    active = net - benchmark_return
    summary = {
        "qlib_version": qlib.__version__,
        "strategy": type(strategy).__name__,
        "variant": args.variant,
        "signal": "equal_weight_leave-one-out_industry_peer_return",
        "execution": "previous-bar signal -> current close orders -> Qlib Account",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "trade_days": int(len(report)),
        "target_days": int(len(targets)),
        "ticker_count": int(targets.shape[1]),
        "mean_eligible_signal_count": float(raw_signal.notna().sum(axis=1).mean()),
        "active_multiplier": args.active_multiplier,
        "top_fraction": args.top_fraction,
        "risk_degree": args.risk_degree,
        "buy_cost": args.buy_cost,
        "sell_cost": args.sell_cost,
        "cumulative_gross_return": _compound(gross),
        "cumulative_net_return": _compound(net),
        "cumulative_benchmark_return": _compound(benchmark_return),
        "cumulative_net_active_return": _compound(active),
        "annualized_net_return": float(net.mean() * 252.0),
        "annualized_benchmark_return": float(benchmark_return.mean() * 252.0),
        "annualized_net_active_return": float(active.mean() * 252.0),
        "net_active_information_ratio": _annualized_ratio(active),
        "annualized_cost": float(cost.mean() * 252.0),
        "mean_daily_turnover": float(report["turnover"].mean()),
        "final_account_value": float(report["account"].iloc[-1]),
    }
    if isinstance(strategy, ConsecutiveLossStopPeerMomentumStrategy):
        summary.update(
            {
                "consecutive_loss_days": strategy.consecutive_loss_days,
                "stop_triggered": strategy.stop_triggered,
                "stop_trigger_date": _optional_date(strategy.stop_trigger_date),
                "liquidation_decision_date": _optional_date(
                    strategy.liquidation_decision_date
                ),
            }
        )
    return summary


def _optional_date(value: pd.Timestamp | None) -> str | None:
    return None if value is None else pd.Timestamp(value).strftime("%Y-%m-%d")


def _compound(values: pd.Series) -> float:
    clean = values.dropna().astype("float64")
    return float(clean.add(1.0).prod() - 1.0) if not clean.empty else float("nan")


def _annualized_ratio(values: pd.Series) -> float:
    clean = values.dropna().astype("float64")
    std = float(clean.std(ddof=1))
    if clean.empty or not np.isfinite(std) or std <= 0.0:
        return float("nan")
    return float(clean.mean() / std * np.sqrt(252.0))


def _write_outputs(
    output_dir: Path,
    report: pd.DataFrame,
    indicators: pd.DataFrame,
    benchmark_return: pd.Series,
    targets: pd.DataFrame,
    active_weights: pd.DataFrame,
    raw_signal: pd.DataFrame,
    summary: dict[str, object],
    positions: dict,
    feedback_history: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report.join(benchmark_return).to_csv(output_dir / "portfolio_metrics.csv")
    indicators.to_csv(output_dir / "trade_indicators.csv")
    targets.to_parquet(output_dir / "target_weights.parquet")
    active_weights.to_parquet(output_dir / "active_weights.parquet")
    raw_signal.to_parquet(output_dir / "raw_peer_signal.parquet")
    pd.to_pickle(positions, output_dir / "positions.pkl")
    if not feedback_history.empty:
        feedback_history.to_csv(output_dir / "portfolio_feedback.csv")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
