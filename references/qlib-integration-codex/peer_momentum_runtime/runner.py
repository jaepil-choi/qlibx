from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import qlib
import yaml
from qlib.backtest import backtest
from qlib.backtest.executor import SimulatorExecutor
from qlib.constant import REG_US

from kwam_enhanced_index.config import ProjectConfig, load_config
from kwam_enhanced_index.orchestration.configuration.portfolio import (
    build_buffer_budget_spec,
    build_enhanced_index_methods,
    resolve_alpha_multiplier,
    select_default_enhanced_index_method,
)
from peer_momentum_runtime.data import QlibPeerMomentumData
from peer_momentum_runtime.exchange import (
    KrxPandasExchange,
    build_quote_frame,
)
from peer_momentum_runtime.strategy import QlibPeerMomentumStrategy


# 역할: read-only project config, Qlib twin, executor, artifact 출력을 조립합니다.
# 책임:
# - signal이나 target을 계산하지 않습니다.
# - Qlib backtest loop가 strategy lifecycle을 소유하도록 객체만 구성합니다.


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIG_PATH = INTEGRATION_ROOT / "configs" / "peer_momentum.yaml"


@dataclass(frozen=True)
class QlibPeerMomentumRunResult:
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    output_dir: Path
    report: pd.DataFrame
    indicators: pd.DataFrame
    strategy: QlibPeerMomentumStrategy
    exchange: KrxPandasExchange
    summary: Mapping[str, Any]


def run_qlib_peer_momentum(
    *,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp | None = None,
    output_dir: Path | None = None,
    config: ProjectConfig | None = None,
    runtime_config: Mapping[str, Any] | None = None,
) -> QlibPeerMomentumRunResult:
    project = config or load_config()
    runtime_root = runtime_config or _load_runtime_config(RUNTIME_CONFIG_PATH)
    runtime = _required_mapping(
        runtime_root,
        "peer_momentum",
        "qlib-integration-codex.configs.peer_momentum",
    )
    etf_ticker = _required_str(runtime, "physical_etf_ticker")
    data = QlibPeerMomentumData.from_project_config(
        project,
        etf_ticker=etf_ticker,
        peer_group_dataset=_required_str(runtime, "peer_group_dataset"),
    )
    resolved_start, resolved_end = data.resolve_run_dates(start_date, end_date)
    dates = data.calendar[
        (data.calendar >= resolved_start) & (data.calendar <= resolved_end)
    ]
    physical = data.physical_columns

    destination = (
        output_dir
        if output_dir is not None
        else INTEGRATION_ROOT / "outputs" / "native_peer_momentum"
    ).resolve()
    provider_dir = destination / "provider"
    _write_minimal_provider(provider_dir, dates, physical)
    qlib.init(
        provider_uri=str(provider_dir),
        region=REG_US,
        expression_cache=None,
        dataset_cache=None,
    )

    quote = build_quote_frame(
        data.execution_price.loc[dates],
        data.position_unit_factor.loc[dates],
        data.volume.loc[dates],
        data.buyable.loc[dates],
        data.sellable.loc[dates],
        data.suspended.loc[dates],
        max_volume_participation=float(runtime["max_volume_participation"]),
    )
    participation = float(runtime["max_volume_participation"])
    lot_config = _required_mapping(runtime, "lot_size", "qlib.peer_momentum")
    lot_size = pd.Series(
        {
            instrument: int(lot_config[str(data.asset_class.loc[instrument])])
            for instrument in physical
        },
        dtype="int64",
    )
    exchange = KrxPandasExchange(
        quote_frame=quote,
        asset_class=data.asset_class.to_dict(),
        cost_policy=_cost_policy(project.backtest),
        lot_size=lot_size.to_dict(),
        freq="day",
        start_time=resolved_start,
        end_time=resolved_end,
        codes=physical.tolist(),
        deal_price="close",
        limit_threshold=("$limit_buy", "$limit_sell"),
        volume_threshold=("cum", "$volume_limit") if participation else None,
        open_cost=0.0,
        close_cost=0.0,
        min_cost=0.0,
        impact_cost=0.0,
        trade_unit=None,
        subscribe_fields=["$suspended"],
    )
    portfolio_method = _build_default_portfolio_method(
        project,
        definition_name=_required_str(runtime, "cash_frame_definition"),
    )
    strategy = QlibPeerMomentumStrategy(
        strategy_id=_required_str(runtime, "strategy_id"),
        data=data,
        portfolio_method=portfolio_method,
        alpha_multiplier=resolve_alpha_multiplier(project.enhanced_index),
        top_fraction=float(runtime["top_fraction"]),
        decay_window=int(runtime["decay_window"]),
        decay_dense=bool(runtime["decay_dense"]),
        risk_degree=float(runtime["risk_degree"]),
    )
    executor = SimulatorExecutor(
        time_per_step="day",
        generate_portfolio_metrics=True,
        verbose=False,
    )
    benchmark_return = (
        data.benchmark_weight.loc[dates] * data.returns.loc[dates]
    ).sum(axis=1, min_count=1).fillna(0.0)
    portfolio_metrics, indicator_metrics = backtest(
        start_time=resolved_start,
        end_time=resolved_end,
        strategy=strategy,
        executor=executor,
        benchmark=benchmark_return,
        account=float(runtime["account"]),
        exchange_kwargs={"exchange": exchange},
    )
    report, _qlib_positions = portfolio_metrics["1day"]
    indicators, _indicator_object = indicator_metrics["1day"]
    reconciliation_error = _validate_account_reconciliation(report)
    summary = _build_summary(
        strategy=strategy,
        report=report,
        benchmark_return=benchmark_return.reindex(report.index).fillna(0.0),
        start_date=resolved_start,
        end_date=resolved_end,
        etf_ticker=etf_ticker,
        account_reconciliation_max_abs_error=reconciliation_error,
    )
    _write_artifacts(
        destination,
        strategy,
        exchange,
        report,
        indicators,
        benchmark_return.reindex(report.index),
        summary,
    )
    return QlibPeerMomentumRunResult(
        start_date=resolved_start,
        end_date=resolved_end,
        output_dir=destination,
        report=report,
        indicators=indicators,
        strategy=strategy,
        exchange=exchange,
        summary=summary,
    )


def _build_default_portfolio_method(
    config: ProjectConfig,
    *,
    definition_name: str,
):
    definitions = _required_mapping(config.ensemble, "definitions", "ensemble")
    definition = _required_mapping(definitions, definition_name, "ensemble.definitions")
    cash_frame = _required_mapping(
        definition,
        "cash_frame",
        f"ensemble.definitions.{definition_name}",
    )
    canonical = build_buffer_budget_spec(
        _required_mapping(
            cash_frame,
            "buffer_budget",
            f"ensemble.definitions.{definition_name}.cash_frame",
        )
    )
    methods = build_enhanced_index_methods(
        config.enhanced_index,
        config.constraints,
        canonical_cash_buffer_budget=canonical,
    )
    return select_default_enhanced_index_method(methods)


def _cost_policy(backtest_config: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    costs = _required_mapping(backtest_config, "costs", "backtest")
    enabled = bool(costs["enabled"])
    scale = 1e-4 if enabled else 0.0
    base = {
        "buy_rate": float(costs["buy_fee_bp"]) * scale,
        "sell_rate": float(costs["sell_fee_bp"]) * scale,
        "sell_tax": float(costs["sell_tax_bp"]) * scale,
    }
    result = {"stock": dict(base), "etf": dict(base)}
    overrides = costs.get("policy_overrides", {})
    if not isinstance(overrides, Mapping):
        raise TypeError("backtest.costs.policy_overrides must be a mapping.")
    for asset_class, values in overrides.items():
        if asset_class not in result:
            raise ValueError(f"Unknown execution cost asset class: {asset_class}")
        if not isinstance(values, Mapping):
            raise TypeError(f"Cost override must be a mapping: {asset_class}")
        key_map = {
            "buy_fee_bp": "buy_rate",
            "sell_fee_bp": "sell_rate",
            "sell_tax_bp": "sell_tax",
        }
        unknown = sorted(set(values) - set(key_map))
        if unknown:
            raise ValueError(f"Unknown cost override fields for {asset_class}: {unknown}")
        for source_key, value in values.items():
            result[str(asset_class)][key_map[source_key]] = float(value) * scale
    return result


def _write_minimal_provider(
    provider_dir: Path,
    calendar: pd.DatetimeIndex,
    instruments: pd.Index,
) -> None:
    calendars_dir = provider_dir / "calendars"
    instruments_dir = provider_dir / "instruments"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    sentinel = pd.Timestamp(calendar[-1]) + pd.offsets.BDay(1)
    calendar_lines = [date.strftime("%Y-%m-%d") for date in calendar]
    calendar_lines.append(sentinel.strftime("%Y-%m-%d"))
    (calendars_dir / "day.txt").write_text(
        "\n".join(calendar_lines) + "\n",
        encoding="utf-8",
    )
    first = calendar[0].strftime("%Y-%m-%d")
    last = sentinel.strftime("%Y-%m-%d")
    (instruments_dir / "all.txt").write_text(
        "\n".join(f"{instrument}\t{first}\t{last}" for instrument in instruments)
        + "\n",
        encoding="utf-8",
    )


def _write_artifacts(
    output_dir: Path,
    strategy: QlibPeerMomentumStrategy,
    exchange: KrxPandasExchange,
    report: pd.DataFrame,
    indicators: pd.DataFrame,
    benchmark_return: pd.Series,
    summary: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _history_frame(strategy.raw_signal_history).to_parquet(output_dir / "signals.parquet")
    _history_frame(strategy.decayed_signal_history).to_parquet(
        output_dir / "decayed_signals.parquet"
    )
    _history_frame(strategy.active_weight_history).to_parquet(
        output_dir / "active_weights.parquet"
    )
    _history_frame(strategy.physical_target_history).to_parquet(
        output_dir / "physical_targets.parquet"
    )
    pd.DataFrame(exchange.execution_history).to_parquet(output_dir / "fills.parquet")
    pd.DataFrame(strategy.position_history).to_parquet(output_dir / "positions.parquet")
    pd.DataFrame(strategy.feedback_history).to_parquet(output_dir / "account_daily.parquet")
    report.to_parquet(output_dir / "qlib_report.parquet")
    indicators.to_parquet(output_dir / "qlib_indicators.parquet")
    benchmark_return.rename("benchmark_return").to_frame().to_parquet(
        output_dir / "benchmark_return.parquet"
    )
    observation = pd.Series(strategy.observation_dates, name="observation_date")
    observation.index.name = "trade_date"
    observation.to_frame().to_parquet(output_dir / "observation_dates.parquet")
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _history_frame(history: Mapping[pd.Timestamp, pd.Series]) -> pd.DataFrame:
    if not history:
        return pd.DataFrame()
    frame = pd.DataFrame.from_dict(history, orient="index").sort_index()
    frame.index = pd.DatetimeIndex(frame.index, name="trade_date")
    return frame


def _build_summary(
    *,
    strategy: QlibPeerMomentumStrategy,
    report: pd.DataFrame,
    benchmark_return: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    etf_ticker: str,
    account_reconciliation_max_abs_error: float,
) -> dict[str, Any]:
    gross_return = report["return"].astype("float64")
    cost = report["cost"].astype("float64")
    net_return = gross_return - cost
    active_return = net_return - benchmark_return
    trading_days = max(len(report), 1)
    return {
        "execution_backend": "qlib",
        "qlib_version": qlib.__version__,
        "strategy_class": (
            f"{type(strategy).__module__}.{type(strategy).__name__}"
        ),
        "strategy_id": strategy.strategy_id,
        "start_date": start_date,
        "end_date": end_date,
        "physical_etf_ticker": etf_ticker,
        "decision_count": strategy.decision_count,
        "feedback_count": len(strategy.feedback_history),
        "cumulative_net_return": float((1.0 + net_return).prod() - 1.0),
        "annualized_net_return": float((1.0 + net_return).prod() ** (252 / trading_days) - 1.0),
        "annualized_active_return": float(active_return.mean() * 252),
        "annualized_turnover": float(report["turnover"].mean() * 252),
        "total_cost": float(cost.sum()),
        "ending_nav": float(report["account"].iloc[-1]),
        "ending_cash": float(report["cash"].iloc[-1]),
        "account_reconciliation_max_abs_error": (
            account_reconciliation_max_abs_error
        ),
    }


def _validate_account_reconciliation(report: pd.DataFrame) -> float:
    required = {"account", "value", "cash"}
    missing = sorted(required - set(report.columns))
    if missing:
        raise KeyError(f"Qlib portfolio report is missing fields: {missing}")
    values = report.loc[:, ["account", "value", "cash"]].astype("float64")
    if values.empty or not np.isfinite(values.to_numpy()).all():
        raise ValueError("Qlib portfolio report must contain finite account values.")
    error = (values["account"] - values["value"] - values["cash"]).abs()
    tolerance = np.maximum(values["account"].abs() * 1e-10, 1e-6)
    failed = error.gt(tolerance)
    if failed.any():
        date = pd.Timestamp(error.index[failed][0]).normalize()
        raise RuntimeError(
            "Qlib account reconciliation failed: "
            f"date={date.date()}, error={float(error.loc[failed].iloc[0])}"
        )
    return float(error.max())


def _required_mapping(
    config: Mapping[str, Any],
    key: str,
    prefix: str,
) -> Mapping[str, Any]:
    if key not in config:
        raise KeyError(f"Missing config mapping: {prefix}.{key}")
    value = config[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"Config value must be a mapping: {prefix}.{key}")
    return value


def _load_runtime_config(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Qlib twin config: {path}")
    with path.open("r", encoding="utf-8") as file:
        value = yaml.safe_load(file) or {}
    if not isinstance(value, Mapping):
        raise TypeError(f"Qlib twin config must be a mapping: {path}")
    return value


def _required_str(config: Mapping[str, Any], key: str) -> str:
    if key not in config or not isinstance(config[key], str) or not config[key]:
        raise ValueError(f"Config value must be a non-empty string: {key}")
    return str(config[key])
