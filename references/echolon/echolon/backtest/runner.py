"""
Run Backtest - Public API
=========================

Unified entry point for running backtests with the quant engine.

This module provides simple function-based API for common use cases:
- run_debug_backtest(ctx): Quick iteration with DEFAULT_PARAMS
- run_best_trial(ctx): Run with optimized parameters
- run_backtest(ctx, ...): Custom parameters

All functions use TradingContext as single source of truth for market/instrument config.
Use MarketFactory.create(...) to build ctx with explicit market/instrument values
(host apps own session parsing).

For more control, use the class-based API directly:
- BacktestRunner: Full-featured runner for debug/best_trial modes
- OptimizationRunner: Lightweight runner for Optuna optimization

Usage:
------
    from echolon.config.markets.factory import MarketFactory
    from echolon.backtest.runner import run_debug_backtest, run_best_trial

    # Get TradingContext (single source of truth)
    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )

    # Debug backtest
    results = run_debug_backtest(ctx)

    # Best trial backtest
    results = run_best_trial(ctx)

    # Custom parameters
    from echolon.backtest.runner import run_backtest
    results = run_backtest(ctx, strategy_params={'entry_params': {...}, 'exit_params': {...}})

    # Class-based API for more control
    from echolon.backtest.engine.backtest_runner import BacktestRunner
    runner = BacktestRunner(ctx=ctx)
    results = runner.load_data().run(params=my_params, context='custom')

    # Command line
    python -m echolon.backtest.runner --mode debug --market SHFE --instrument al --frequency interday --bar-size 1d
    python -m echolon.backtest.runner --mode best_trial --market SHFE --instrument al --frequency interday --bar-size 1d
"""

import argparse
import logging
from typing import Dict, Any, Optional

from echolon.config.markets.core.context import TradingContext
from echolon.config.backtest_config import BacktestConfig
from echolon.config.paths_config import PathsConfig
from .engine.backtest_runner import BacktestRunner, _RunnerConfig

logger = logging.getLogger(__name__)


# =============================================================================
# Public API Functions
# =============================================================================

def run_backtest(
    ctx: TradingContext,
    strategy_params: Optional[Dict[str, Any]] = None,
    run_context: str = 'backtest',
    enable_strategy_logging: bool = True,
    output_dir: Optional[str] = None,
    save_results: bool = True,
    backtest_config: Optional[BacktestConfig] = None,
    *,
    paths: PathsConfig,
) -> Dict[str, Any]:
    """
    Run a single backtest with provided parameters.

    This is the main entry point for running custom backtests.
    For quick debug or best_trial runs, use the dedicated functions.

    Parameters
    ----------
    ctx : TradingContext
        Trading context (single source of truth for market/instrument config)
    strategy_params : Dict[str, Any], optional
        Strategy parameters. Uses DEFAULT_PARAMS if None.
    run_context : str
        Run context for logging ('debug', 'best_trial', 'custom')
    enable_strategy_logging : bool
        Enable detailed CSV logging
    output_dir : str, optional
        Output directory for results
    save_results : bool
        Save results to files

    Returns
    -------
    Dict[str, Any]
        Detailed backtest results

    Note
    ----
    - Market and instrument config come from ctx (TradingContext).
    - Futures-specific components (contract-aware broker) are automatically
      enabled based on ctx.has_contract_expiry.
    - Commission and multiplier are retrieved from market_adapter.get_contract_spec().
    """
    # Build internal runner config
    config = _RunnerConfig(
        enable_strategy_logging=enable_strategy_logging,
    )

    if output_dir:
        config.backtest_results_dir = output_dir

    # Create runner with ctx and execute
    runner = BacktestRunner(
        ctx=ctx, paths=paths, config=config, backtest_config=backtest_config,
    )
    runner.load_data()

    # Get default params if not provided
    if strategy_params is None:
        from .strategy.platform_agnostic.strategy_params import DEFAULT_PARAMS
        strategy_params = DEFAULT_PARAMS

    return runner.run(
        params=strategy_params,
        context=run_context,
        save_results=save_results,
    )


def run_debug_backtest(
    ctx: TradingContext,
    backtest_config: Optional[BacktestConfig] = None,
    *,
    paths: PathsConfig,
) -> Dict[str, Any]:
    """
    Run debug backtest with default parameters and detailed logging.

    This is the quick iteration mode for strategy development.
    Uses DEFAULT_PARAMS from the strategy module.

    Parameters
    ----------
    ctx : TradingContext
        Trading context (single source of truth for market/instrument config)

    Returns
    -------
    Dict[str, Any]
        Detailed backtest results
    """
    logger.info(
        f"[DEBUG] Starting debug backtest | "
        f"market={ctx.market_code}, instrument={ctx.instrument_name}"
    )

    results = BacktestRunner.debug(ctx, backtest_config=backtest_config, paths=paths)

    # Log result summary
    logger.info(
        f"[DEBUG] Backtest::SUCCESS | "
        f"sharpe={results.get('sharpe_ratio_annual', 0):.3f}, "
        f"return={results.get('total_return_pct', 0):.2f}%, "
        f"max_dd={results.get('max_drawdown_pct', 0):.2f}%, "
        f"trades={results.get('total_trades', 0)}, "
        f"win_rate={results.get('win_rate_pct', 0):.1f}%"
    )

    return results


def run_best_trial(
    ctx: TradingContext,
    best_params_path: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    backtest_config: Optional[BacktestConfig] = None,
    *,
    paths: PathsConfig,
) -> Dict[str, Any]:
    """
    Run backtest with best parameters from Optuna optimization.

    Loads parameters from selected_robust_trial.json and runs backtest.

    Parameters
    ----------
    ctx : TradingContext
        Trading context (single source of truth for market/instrument config)
    best_params_path : str, optional
        Path to best params JSON. Uses default if None.
    start_date : str, optional
        Override backtest start date (e.g. OOS_START_DATE for out-of-sample).
    end_date : str, optional
        Override backtest end date (e.g. OOS_END_DATE for out-of-sample).

    Returns
    -------
    Dict[str, Any]
        Detailed backtest results
    """
    logger.info(
        f"[BEST_TRIAL] Starting best trial backtest | "
        f"market={ctx.market_code}, instrument={ctx.instrument_name}, "
        f"period={start_date or 'default'} to {end_date or 'default'}"
    )

    results = BacktestRunner.best_trial(
        ctx=ctx, params_path=best_params_path,
        start_date=start_date, end_date=end_date,
        backtest_config=backtest_config,
        paths=paths,
    )

    # Log result summary
    logger.info(
        f"[BEST_TRIAL] Backtest::SUCCESS | "
        f"sharpe={results.get('sharpe_ratio_annual', 0):.3f}, "
        f"return={results.get('total_return_pct', 0):.2f}%, "
        f"max_dd={results.get('max_drawdown_pct', 0):.2f}%, "
        f"trades={results.get('total_trades', 0)}, "
        f"win_rate={results.get('win_rate_pct', 0):.1f}%"
    )

    return results


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Command line entry point."""
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()
    parser = argparse.ArgumentParser(
        description='Run backtest with quant engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m echolon.backtest.runner --mode debug --market SHFE --instrument al --frequency interday --bar-size 1d
    python -m echolon.backtest.runner --mode best_trial --market SHFE --instrument al --frequency interday --bar-size 1d
        """
    )
    parser.add_argument(
        '--mode',
        choices=['debug', 'best_trial'],
        default='debug',
        help='Backtest mode (default: debug)'
    )
    parser.add_argument(
        '--params-path',
        help='Path to parameters JSON (for best_trial mode)'
    )
    parser.add_argument('--market', required=True, help='Market code (e.g., SHFE)')
    parser.add_argument('--instrument', required=True, help='Instrument code (e.g., al)')
    parser.add_argument('--frequency', default='interday', help='interday or intraday')
    parser.add_argument('--bar-size', default='1d', help='Bar size (1m/5m/15m/30m/1h/1d)')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Build TradingContext from explicit CLI args — host apps wire their own
    # session parsing; echolon's CLI is a minimal example.
    from echolon.config.markets.factory import MarketFactory
    ctx = MarketFactory.create(
        market=args.market,
        instrument=args.instrument,
        frequency=args.frequency,
        bar_size=args.bar_size,
    )

    paths = PathsConfig.from_env()
    if args.mode == 'debug':
        results = run_debug_backtest(ctx, paths=paths)
    else:
        results = run_best_trial(ctx, best_params_path=args.params_path, paths=paths)

    # Print summary
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Market:       {ctx.market_code}")
    print(f"Instrument:   {ctx.instrument_name} ({ctx.instrument_code})")
    print(f"Sharpe Ratio: {results.get('sharpe_ratio_annual', 0):.3f}")
    print(f"Total Return: {results.get('total_return_pct', 0):.2f}%")
    print(f"Max Drawdown: {results.get('max_drawdown_pct', 0):.2f}%")
    print(f"Total Trades: {results.get('total_trades', 0)}")
    print(f"Win Rate:     {results.get('win_rate_pct', 0):.1f}%")
    print("=" * 60)


if __name__ == '__main__':
    main()
