"""
Portfolio Backtest Runner
=========================

Runs BacktestRunner per slot independently, combines equity curves,
and computes portfolio-level metrics.

Usage:
    from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig
    from echolon.backtest.portfolio_runner import PortfolioBacktestRunner

    config = PortfolioDeployConfig.load("session/portfolio_deploy_config.json")
    runner = PortfolioBacktestRunner(config)
    results = runner.run()
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from echolon.config.markets.factory import MarketFactory
from echolon.config.optuna_config import OptunaConfig
from echolon.config.backtest_config import BacktestConfig
from .engine.backtest_runner import BacktestRunner
from echolon.backtest.metrics.portfolio_metrics import (
    compute_correlation_matrix,
    compute_per_year_returns,
    compute_portfolio_metrics,
    validate_margin,
)
from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig, SlotConfig

logger = logging.getLogger(__name__)


class PortfolioBacktestRunner:
    """
    Run per-slot backtests and combine into portfolio results.
    """

    def __init__(
        self,
        config: PortfolioDeployConfig,
        output_dir: str = "workspace/portfolio_backtest",
        backtest_config: Optional[BacktestConfig] = None,
        optuna_config: Optional[OptunaConfig] = None,
        *,
        paths: "PathsConfig",  # type: ignore[name-defined]
    ):
        if backtest_config is None:
            raise ValueError(
                "backtest_config is required. Build one with BacktestConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._backtest_config = backtest_config

        if optuna_config is None:
            raise ValueError(
                "optuna_config is required. Build one with OptunaConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._optuna_config = optuna_config

        self.config = config
        self._paths = paths
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run all enabled slots and combine results.

        Args:
            start_date: Override backtest start date (e.g. '2026-01-01').
            end_date: Override backtest end date (e.g. '2026-03-30').

        Returns:
            Dict with per-slot results, combined metrics, correlation,
            and margin validation.
        """
        enabled_slots = self.config.get_enabled_slots()
        logger.info(f"Portfolio backtest: {len(enabled_slots)} slots")

        per_slot_results: Dict[str, Any] = {}
        per_slot_equity: Dict[str, pd.Series] = {}
        per_slot_trades: Dict[str, List[Dict]] = {}
        slot_configs: Dict[str, SlotConfig] = {}

        total_initial = 0.0

        for sc in enabled_slots:
            logger.info(f"Running slot: {sc.slot_id}")
            try:
                result, equity = self._run_slot(sc, start_date, end_date)
                per_slot_results[sc.slot_id] = result
                slot_configs[sc.slot_id] = sc
                if equity is not None:
                    per_slot_equity[sc.slot_id] = equity
                # Extract trades list for margin computation
                per_slot_trades[sc.slot_id] = _extract_trades(result)
                total_initial += sc.initial_capital
            except Exception as e:
                logger.error(f"Slot {sc.slot_id} failed: {e}")
                per_slot_results[sc.slot_id] = {"status": "error", "error": str(e)}

        # Combine equity curves
        combined_equity = self._combine_equity_curves(per_slot_equity)

        # Compute portfolio metrics
        portfolio_metrics = {}
        if combined_equity is not None and not combined_equity.empty:
            portfolio_metrics = compute_portfolio_metrics(
                combined_equity=combined_equity,
                per_slot_equity=per_slot_equity,
                initial_capital=total_initial,
            )

        # Correlation matrix
        corr_matrix = compute_correlation_matrix(per_slot_equity)

        # Margin validation from trade logs
        per_slot_margin = _compute_margin_from_trades(
            per_slot_trades=per_slot_trades,
            per_slot_equity=per_slot_equity,
            slot_configs=slot_configs,
        )
        margin_validation = validate_margin(
            per_slot_equity=per_slot_equity,
            per_slot_margin=per_slot_margin,
            max_total_capital=self.config.deploy.max_total_capital,
        )

        # Per-year returns from full continuous backtest
        per_year = compute_per_year_returns(combined_equity, per_slot_equity) if combined_equity is not None else {'years': []}

        results = {
            'portfolio_metrics': portfolio_metrics,
            'per_year_returns': per_year,
            'per_slot_results': per_slot_results,
            'correlation_matrix': corr_matrix.to_dict() if corr_matrix is not None else None,
            'margin_validation': margin_validation,
        }

        # Save results
        self._save_results(results, combined_equity, per_slot_equity)

        return results

    def _create_slot_context(self, sc: SlotConfig) -> 'TradingContext':
        """Create TradingContext for a slot with correct initial_capital."""
        return MarketFactory.create(
            market=sc.market,
            instrument=sc.instrument_code,
            frequency=sc.frequency,
            bar_size=sc.bar_size,
            initial_capital=sc.initial_capital,
        )

    def _run_slot(
        self,
        sc: SlotConfig,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        """Run a single slot's backtest using its own strategy code directory."""
        ctx = self._create_slot_context(sc)

        # Use best_trial with the slot's strategy_code_dir so it loads
        # strategy.py, strategy_params.py, and selected_robust_trial.json
        # from the slot directory (e.g., strategy/al_s1/) instead of
        # platform_agnostic/.
        result = BacktestRunner.best_trial(
            ctx=ctx,
            strategy_code_dir=sc.strategy_code_dir,
            start_date=start_date,
            end_date=end_date,
            backtest_config=self._backtest_config,
            paths=self._paths,
        )

        # Extract equity curve from result (list of {'date': str, 'equity': float})
        equity = None
        if isinstance(result, dict) and 'equity_curve' in result:
            ec = result['equity_curve']
            if ec and isinstance(ec, list) and len(ec) > 0:
                df = pd.DataFrame(ec)
                df['date'] = pd.to_datetime(df['date'])
                equity = df.set_index('date')['equity']

        return result, equity

    def run_per_window(
        self,
        windows: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Run independent portfolio backtests per time window.

        Each window starts with fresh initial capital — same as WFA OOS
        evaluation but at the portfolio level.

        Args:
            windows: List of {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'}.
                Defaults to annual windows 2020-2025.

        Returns:
            Dict with per-window portfolio metrics.
        """
        if windows is None:
            windows = [
                {'start': f'{y}-01-01', 'end': f'{y}-12-31'}
                for y in range(2020, 2026)
            ]

        enabled_slots = self.config.get_enabled_slots()
        total_initial = sum(sc.initial_capital for sc in enabled_slots)
        window_results = []

        for window in windows:
            start, end = window['start'], window['end']
            label = f"{start[:4]}" if start[:4] == end[:4] else f"{start}_{end}"
            logger.info(f"Window {label}: {start} to {end}")

            per_slot_equity: Dict[str, pd.Series] = {}

            for sc in enabled_slots:
                try:
                    equity = self._run_slot_window(sc, start, end)
                    if equity is not None and not equity.empty:
                        per_slot_equity[sc.slot_id] = equity
                except Exception as e:
                    logger.error(f"  [{sc.slot_id}] Window {label} failed: {e}")

            if not per_slot_equity:
                window_results.append({
                    'window': label, 'start': start, 'end': end,
                    'status': 'failed', 'error': 'No equity curves',
                })
                continue

            combined = self._combine_equity_curves(per_slot_equity)
            if combined is None or combined.empty:
                window_results.append({
                    'window': label, 'start': start, 'end': end,
                    'status': 'failed', 'error': 'Empty combined equity',
                })
                continue

            metrics = compute_portfolio_metrics(
                combined_equity=combined,
                per_slot_equity=per_slot_equity,
                initial_capital=total_initial,
            )

            # Compute return as simple start-to-end for this window
            start_val = float(combined.iloc[0])
            end_val = float(combined.iloc[-1])
            window_return = (end_val / start_val - 1) * 100

            window_results.append({
                'window': label,
                'start': start,
                'end': end,
                'status': 'ok',
                'annual_return_pct': round(window_return, 2),
                'sharpe': metrics.get('sharpe_ratio', 0),
                'max_dd_pct': round(metrics.get('max_drawdown', 0) * 100, 2),
                'trading_days': metrics.get('n_days', 0),
                'slot_returns': {
                    sid: round((float(eq.iloc[-1]) / float(eq.iloc[0]) - 1) * 100, 2)
                    for sid, eq in per_slot_equity.items()
                    if len(eq) >= 2
                },
            })

        return {'windows': window_results}

    def _run_slot_window(
        self, sc: SlotConfig, start_date: str, end_date: str
    ) -> Optional[pd.Series]:
        """Run a single slot for a specific date window."""
        ctx = self._create_slot_context(sc)

        result = BacktestRunner.best_trial(
            ctx=ctx,
            strategy_code_dir=sc.strategy_code_dir,
            start_date=start_date,
            end_date=end_date,
            backtest_config=self._backtest_config,
            paths=self._paths,
        )

        if isinstance(result, dict) and 'equity_curve' in result:
            ec = result['equity_curve']
            if ec and isinstance(ec, list) and len(ec) > 0:
                df = pd.DataFrame(ec)
                df['date'] = pd.to_datetime(df['date'])
                return df.set_index('date')['equity']
        return None

    def _combine_equity_curves(
        self, per_slot_equity: Dict[str, pd.Series]
    ) -> Optional[pd.Series]:
        """Combine per-slot equity curves: align dates, forward-fill, sum."""
        if not per_slot_equity:
            return None

        df = pd.DataFrame(per_slot_equity)
        df = df.sort_index().ffill()
        combined = df.sum(axis=1)
        return combined

    def _save_results(
        self,
        results: Dict[str, Any],
        combined_equity: Optional[pd.Series],
        per_slot_equity: Dict[str, pd.Series],
    ) -> None:
        """Save portfolio backtest results."""
        metrics_path = os.path.join(self.output_dir, "portfolio_metrics.json")
        serializable = _make_serializable(results)
        with open(metrics_path, 'w') as f:
            json.dump(serializable, f, indent=2, default=str)
        logger.info(f"Portfolio metrics saved to {metrics_path}")

        if combined_equity is not None:
            eq_path = os.path.join(self.output_dir, "combined_equity.csv")
            combined_equity.to_csv(eq_path, header=['equity'])

        for slot_id, eq in per_slot_equity.items():
            slot_eq_path = os.path.join(self.output_dir, f"equity_{slot_id}.csv")
            eq.to_csv(slot_eq_path, header=['equity'])


# =============================================================================
# Trade-based margin computation
# =============================================================================

def _extract_trades(result: Any) -> List[Dict]:
    """Extract trade list from backtest result."""
    if not isinstance(result, dict):
        return []
    trades = result.get('trades', [])
    # Handle wrapped format: {'trades': [...]}
    if isinstance(trades, dict) and 'trades' in trades:
        trades = trades['trades']
    if not isinstance(trades, list):
        return []
    return trades


def _compute_margin_from_trades(
    per_slot_trades: Dict[str, List[Dict]],
    per_slot_equity: Dict[str, pd.Series],
    slot_configs: Dict[str, SlotConfig],
) -> Dict[str, pd.Series]:
    """
    Compute per-bar margin from trade logs.

    For each trade (entry_date → exit_date), the position is open and
    uses margin = size * entry_price * multiplier * margin_rate.
    On days between entry and exit, the position is held.

    Returns a dict of slot_id → pd.Series(date → margin_used).
    """
    per_slot_margin: Dict[str, pd.Series] = {}

    for slot_id, trades in per_slot_trades.items():
        equity = per_slot_equity.get(slot_id)
        if equity is None or equity.empty:
            continue

        sc = slot_configs.get(slot_id)
        if sc is None:
            continue

        # Get multiplier and margin_rate from TradingContext
        ctx = MarketFactory.create(
            market=sc.market,
            instrument=sc.instrument_code,
            frequency=sc.frequency,
            bar_size=sc.bar_size,
        )
        multiplier = ctx.multiplier
        margin_rate = ctx.margin_rate

        # Build daily margin series from equity curve dates
        all_dates = equity.index
        margin_series = pd.Series(0.0, index=all_dates)

        for trade in trades:
            entry_date = pd.to_datetime(trade.get('entry_date'))
            exit_date = pd.to_datetime(trade.get('exit_date'))
            size = abs(float(trade.get('size', 0)))
            entry_price = float(trade.get('entry_price', 0))

            if size == 0 or entry_price == 0:
                continue

            trade_margin = size * entry_price * multiplier * margin_rate

            # Mark all dates in [entry_date, exit_date] as having this margin
            mask = (all_dates >= entry_date) & (all_dates <= exit_date)
            margin_series.loc[mask] += trade_margin

        per_slot_margin[slot_id] = margin_series

    return per_slot_margin


def _make_serializable(obj):
    """Convert numpy/pandas types to Python native types for JSON."""
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif isinstance(obj, pd.Series):
        return _make_serializable(obj.to_dict())
    elif isinstance(obj, pd.DataFrame):
        return _make_serializable(obj.to_dict())
    return obj
