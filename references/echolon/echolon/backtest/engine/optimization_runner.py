"""
Optimization Runner
===================

Lightweight backtest runner optimized for Optuna hyperparameter optimization.

Key differences from BacktestRunner:
- No CSV strategy logging (saves I/O)
- No result saving to disk
- Returns only metrics needed for objective function
- Optimized for parallel execution with ProcessPoolExecutor
- Shares data via class variables (copy-on-write in child processes)

Used by OptunaOptimizer for running many parallel backtests during optimization.

Usage:
    from echolon.config.markets.factory import MarketFactory

    # Get TradingContext — host apps own session parsing and pass values here
    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )

    # Setup shared data once (before spawning processes)
    OptimizationRunner.setup_shared_data(
        ctx=ctx,
        indicators=indicators_df,
        market_adapter=adapter,
    )

    # Run individual trials (can be parallelized)
    metrics = OptimizationRunner.run_trial(
        trial_params={'entry_rsi': 30, 'exit_atr': 2.0},
        trial_id=42,
    )
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

import pandas as pd
import numpy as np

from .backtrader_engine import BacktestResults
from .backtrader_strategy import get_strategy_class
from .enriched_pandas_data import get_cached_data_feed_class
from .hooks.contract_aware.broker import preload_contract_prices
from echolon.backtest.logging_utils import setup_backtest_logging
from echolon.config.markets.core.context import TradingContext

if TYPE_CHECKING:
    from echolon.strategy.interfaces import IMarketAdapter

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class OptimizationConfig:
    """Configuration for optimization runs.

    Note:
        Futures-specific components (contract-aware broker, commission, slippage,
        multiplier) are automatically enabled/retrieved from market_adapter.
    """


# =============================================================================
# Metrics Result
# =============================================================================

@dataclass
class OptimizationMetrics:
    """
    Metrics returned from optimization backtest.

    Contains only what's needed for Optuna objective function.
    """
    sharpe_ratio: float
    max_drawdown_pct: float
    annual_return_pct: float
    total_trades: int

    # Optional: set when trial failed
    success: bool = True
    # Structured failure record. When the trial raised, ``failure`` carries
    # the full exception metadata (type, EchelonError code, context,
    # traceback, trial_params, docs_url). The controller aggregates these
    # per-study and renders a terminal summary + JSON artifact when
    # ``n_failed > 0``. See ``echolon.backtest.engine.failure``.
    failure: Optional['OptimizationFailure'] = None
    # Per-trial daily returns: {date_str: return_float}.
    # Populated when the backtest engine's 'timereturn' analyzer runs.
    # None when the analyzer is absent or produced no data.
    # Size note: ~4k days × 50 trials ≈ few MB across a full study.
    daily_returns: Optional[Dict[str, float]] = None

    @classmethod
    def failed(cls, error_message: str) -> 'OptimizationMetrics':
        """Create a failed metrics result from a bare message.

        DEPRECATED — prefer :meth:`failed_from_exc` to preserve the full
        exception structure. This constructor stays as a back-compat
        fallback for call sites that don't have access to the original
        exception (e.g., shared-data pre-checks).
        """
        from echolon.backtest.engine.failure import OptimizationFailure
        return cls(
            sharpe_ratio=-1.0,
            max_drawdown_pct=-999.0,
            annual_return_pct=-100.0,
            total_trades=0,
            success=False,
            failure=OptimizationFailure(
                error_type="PreconditionError",
                message=error_message,
            ),
        )

    @classmethod
    def failed_from_exc(
        cls,
        exc: BaseException,
        trial_params: Optional[Dict[str, Any]] = None,
    ) -> 'OptimizationMetrics':
        """Create a failed metrics result from a live exception.

        Extracts EchelonError's structured fields (code, context, docs_url)
        when present, and tail-truncates the traceback. The resulting
        ``OptimizationFailure`` survives the worker→controller IPC (it's a
        plain dataclass of JSON-serializable values).
        """
        from echolon.backtest.engine.failure import OptimizationFailure
        return cls(
            sharpe_ratio=-1.0,
            max_drawdown_pct=-999.0,
            annual_return_pct=-100.0,
            total_trades=0,
            success=False,
            failure=OptimizationFailure.from_exception(exc, trial_params=trial_params),
        )

    @property
    def error_message(self) -> Optional[str]:
        """Back-compat accessor: return the structured failure's message.

        Existing callers read ``metrics.error_message`` as a string. Keep
        the attribute as a read-only view onto ``failure.message`` for one
        release; new code should consume ``metrics.failure`` directly.
        """
        return self.failure.message if self.failure is not None else None

    def get_multi_objective_values(self) -> tuple:
        """Get values for multi-objective optimization (sharpe, -drawdown, return)."""
        return (self.sharpe_ratio, -self.max_drawdown_pct, self.annual_return_pct)

    def get_single_objective_value(self, target: str) -> float:
        """Get value for single-objective optimization."""
        if target == "sharpe_ratio":
            return self.sharpe_ratio
        elif target == "total_return":
            return self.annual_return_pct
        elif target == "drawdown":
            return -self.max_drawdown_pct
        else:
            # Default: risk-adjusted return
            if self.max_drawdown_pct > 0:
                return self.annual_return_pct / (1 + self.max_drawdown_pct)
            return self.annual_return_pct


# =============================================================================
# OptimizationRunner Class
# =============================================================================

class OptimizationRunner:
    """
    Lightweight backtest runner for Optuna optimization.

    Uses class-level shared data for efficient process pool execution.
    Child processes inherit shared data via copy-on-write.

    Class Methods
    -------------
    setup_shared_data(ctx, **kwargs)
        Setup shared data before optimization (call once in main process)

    run_trial(trial_params, trial_id)
        Run single backtest with trial parameters (parallelizable)

    preload_contracts(indicators_dir)
        Pre-load contract prices for O(1) lookups
    """

    # Shared data for child processes (copy-on-write)
    # Note: strategy_class is NOT stored here - it's recreated in each process
    # via get_strategy_class(ctx) to avoid pickle issues with dynamic classes
    _shared_data: Dict[str, Any] = {
        'indicators': None,
        'indicator_metadata': None,  # For creating data feed class
        'market_adapter': None,
        'ctx': None,  # TradingContext (single source of truth)
        'segmentation_data': None,
        'indicators_dir': None,  # Per-instrument indicators dir (e.g. indicators_backtest_dir/{instrument}/)
        'indicators_backtest_dir': None,  # Indicators ROOT dir — threaded to bridge for slot lookup
        'strategy_code_dir': None,  # Strategy code dir — threaded to bridge to avoid env fallback
        'market_data_dir': None,  # Market-data ROOT dir — threaded to SHFE adapter for main_contract.csv
        'optimization_config': None,
    }

    @classmethod
    def setup_shared_data(
        cls,
        ctx: TradingContext,
        indicators: pd.DataFrame,
        market_adapter: 'IMarketAdapter',
        indicators_dir: Optional[str] = None,
        indicators_backtest_dir: Optional[str] = None,
        strategy_code_dir: Optional[str] = None,
        market_data_dir: Optional[str] = None,
        segmentation_data: Optional[pd.DataFrame] = None,
        optimization_config: Optional[OptimizationConfig] = None,
        indicator_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Setup shared data for optimization runs.

        Call this once in the main process before spawning workers.
        Child processes will inherit this data via copy-on-write.

        The strategy class is recreated in each worker process via
        ``get_strategy_class(ctx)`` to avoid pickle issues with dynamic classes.

        Parameters
        ----------
        ctx : TradingContext
            Trading context (single source of truth for market/instrument config)
        indicators : pd.DataFrame
            Market data with indicators (indexed by date)
        strategy_class : type
            Backtrader strategy class (not stored, recreated per-process)
        market_adapter : IMarketAdapter
            Market adapter for market-specific rules
        indicators_dir : str, optional
            Path to indicators directory (for contract-aware broker)
        segmentation_data : pd.DataFrame, optional
            Pre-loaded per-bar categorical column for trade-analyzer
            stratification (e.g., TRS-paradigm 'market_regime').
        optimization_config : OptimizationConfig, optional
            Optimization-specific configuration
        indicator_metadata : Dict[str, Any], optional
            Indicator metadata for creating data feed class
        """
        cls._shared_data['ctx'] = ctx
        cls._shared_data['indicators'] = indicators
        # Note: strategy_class intentionally NOT stored to avoid pickle issues
        # It will be recreated via get_strategy_class(...) in each worker;
        # the worker reads `indicators_backtest_dir` + `strategy_code_dir`
        # from shared data so the bridge's _register_indicators +
        # _initialize_strategy don't need a from_env() fallback.
        cls._shared_data['market_adapter'] = market_adapter
        cls._shared_data['indicators_dir'] = indicators_dir
        cls._shared_data['indicators_backtest_dir'] = indicators_backtest_dir
        cls._shared_data['strategy_code_dir'] = strategy_code_dir
        cls._shared_data['market_data_dir'] = market_data_dir
        cls._shared_data['segmentation_data'] = segmentation_data
        cls._shared_data['optimization_config'] = optimization_config or OptimizationConfig()
        cls._shared_data['indicator_metadata'] = indicator_metadata

        logger.info(
            f"[OPTIMIZATION_RUNNER] Shared data setup | "
            f"rows={len(indicators)}, "
            f"market={ctx.market_code}, instrument={ctx.instrument_name}"
        )

    @classmethod
    def preload_contracts(cls, indicators_dir: str) -> int:
        """
        Pre-load contract prices for O(1) lookups during optimization.

        Call this before running optimization to speed up contract-aware broker.

        Parameters
        ----------
        indicators_dir : str
            Path to indicators directory

        Returns
        -------
        int
            Number of contracts loaded
        """
        contracts_loaded = preload_contract_prices(indicators_dir)
        logger.info(f"[OPTIMIZATION_RUNNER] Pre-loaded {contracts_loaded} contracts")
        return contracts_loaded

    @classmethod
    def run_trial(
        cls,
        trial_params: Dict[str, Any],
        trial_id: int,
    ) -> OptimizationMetrics:
        """
        Run a single backtest with trial parameters.

        This method is designed for parallel execution via ProcessPoolExecutor.
        Uses shared data setup via setup_shared_data().

        Parameters
        ----------
        trial_params : Dict[str, Any]
            Strategy parameters from Optuna trial
        trial_id : int
            Trial number for logging

        Returns
        -------
        OptimizationMetrics
            Metrics for objective function evaluation
        """
        # CRITICAL: Set logging context for child processes
        # ProcessPoolExecutor spawns fresh processes where _current_context
        # defaults to "debug". This suppresses verbose bar-by-bar logging.
        setup_backtest_logging("optimization")

        # Get shared data
        indicators = cls._shared_data['indicators']
        ctx = cls._shared_data['ctx']
        segmentation_data = cls._shared_data['segmentation_data']
        indicators_dir = cls._shared_data['indicators_dir']
        indicators_backtest_dir = cls._shared_data['indicators_backtest_dir']
        strategy_code_dir = cls._shared_data['strategy_code_dir']
        market_data_dir = cls._shared_data['market_data_dir']
        indicator_metadata = cls._shared_data['indicator_metadata']

        if indicators is None or ctx is None:
            return OptimizationMetrics.failed("Shared data not initialized")

        if indicator_metadata is None:
            return OptimizationMetrics.failed("indicator_metadata not set in shared data")

        # Recreate strategy class in this process (avoids pickle issues).
        # Thread the indicators-root + strategy-code dirs into the bridge so
        # _register_indicators reads `indicators_backtest_dir` from its
        # strategy params (rather than raising CFG-003) and
        # _initialize_strategy doesn't fall back to PathsConfig.from_env().
        strategy_class = get_strategy_class(
            ctx,
            strategy_code_dir=strategy_code_dir,
            indicators_backtest_dir=indicators_backtest_dir,
        )

        try:
            # Create engine (lightweight - no logging)
            # Use EngineFactory to handle frequency context and hooks
            from echolon.engine.factory import EngineFactory
            engine = EngineFactory.create_backtest_engine(
                ctx=ctx,
                indicators_dir=indicators_dir,
                strategy_logger_enabled=False,  # No logging during optimization
                market_data_dir=Path(market_data_dir) if market_data_dir else None,
            )

            # Create data feed with cached class using metadata
            DataFeedClass = get_cached_data_feed_class(indicator_metadata)
            data_feed = DataFeedClass(dataname=indicators)

            # Prepare strategy parameters
            strategy_params = {
                'use_precalculated_indicators': True,
                'debug_level': 0,
                'printlog': False,
                **trial_params
            }

            # Setup and run (commission, slippage, multiplier auto-retrieved from market_adapter)
            engine.setup(
                data_feed=data_feed,
                strategy_class=strategy_class,
                strategy_params=strategy_params,
                segmentation_data=segmentation_data,
            )

            results = engine.run()

            if results is None:
                return OptimizationMetrics.failed("Backtest returned None")

            # Extract metrics from analyzers
            return cls._extract_metrics(results)

        except Exception as e:
            # Structured failure — capture the exception with trial_params so
            # the controller can dedup and surface a single aggregated report.
            # Worker-side logging is intentionally omitted: worker loggers
            # don't propagate across ProcessPoolExecutor, so any line here is
            # invisible to the user. The OptunaOptimizer renders from the
            # returned OptimizationFailure instead.
            return OptimizationMetrics.failed_from_exc(e, trial_params=trial_params)

    @classmethod
    def _extract_metrics(cls, results: BacktestResults) -> OptimizationMetrics:
        """Extract optimization metrics from backtest results."""
        analyzers = results.analyzers or {}

        # Get metrics with fallbacks
        sharpe_ratio = results.sharpe_ratio
        if sharpe_ratio is None or np.isnan(sharpe_ratio) or np.isinf(sharpe_ratio):
            sharpe_ratio = -1.0

        max_drawdown = results.max_drawdown
        if max_drawdown is None or np.isnan(max_drawdown) or np.isinf(max_drawdown):
            max_drawdown = -999.0

        # Annual return from analyzers
        annual_return = analyzers.get('average_annual_return_pct', -100.0)
        if annual_return is None or np.isnan(annual_return) or np.isinf(annual_return):
            annual_return = -100.0

        daily_returns: Optional[Dict[str, float]] = analyzers.get('daily_returns') or None

        return OptimizationMetrics(
            sharpe_ratio=float(sharpe_ratio),
            max_drawdown_pct=float(max_drawdown),
            annual_return_pct=float(annual_return),
            total_trades=results.total_trades or 0,
            success=True,
            daily_returns=daily_returns,
        )

    @classmethod
    def clear_shared_data(cls) -> None:
        """Clear shared data after optimization completes."""
        for key in cls._shared_data:
            cls._shared_data[key] = None
        logger.debug("[OPTIMIZATION_RUNNER] Shared data cleared")


# =============================================================================
# Convenience Functions
# =============================================================================

def run_optimization_trial(
    trial_params: Dict[str, Any],
    trial_id: int,
) -> Dict[str, Any]:
    """
    Convenience function for running optimization trial.

    Returns dict format compatible with OptunaOptimizer's parallel execution.

    Parameters
    ----------
    trial_params : Dict[str, Any]
        Strategy parameters from Optuna trial
    trial_id : int
        Trial number

    Returns
    -------
    Dict[str, Any]
        Result dict with 'success', 'values'/'value', 'metrics' keys
    """
    metrics = OptimizationRunner.run_trial(trial_params, trial_id)

    if not metrics.success:
        return {
            'success': False,
            'failure': metrics.failure.to_dict() if metrics.failure else None,
            'critical_error': False,
        }

    return {
        'success': True,
        'values': metrics.get_multi_objective_values(),
        'value': metrics.sharpe_ratio,  # Default single objective
        'metrics': {
            'sharpe_ratio': metrics.sharpe_ratio,
            'max_drawdown_pct': metrics.max_drawdown_pct,
            'annual_return_pct': metrics.annual_return_pct,
            'total_trades': metrics.total_trades,
            'daily_returns': metrics.daily_returns,  # FLAG-2: per-trial returns (pickled across IPC)
        }
    }
