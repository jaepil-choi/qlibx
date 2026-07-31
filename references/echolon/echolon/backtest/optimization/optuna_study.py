"""
Optuna Study Management
=======================

Optuna-based hyperparameter optimization for strategy parameters.

OptunaOptimizer class manages:
- Study creation with configurable sampler and pruner
- Parameter space definition from strategy_params module
- Objective function that runs backtests via BacktraderEngine
- Trial management and persistence
- Parallel execution support with ProcessPoolExecutor

Features:
- Pre-loads contract prices for O(1) lookups during optimization
- Error classification: recoverable vs critical errors
- Progress logging with ETA
- Multi-objective optimization support

Usage:
    from echolon.config.markets.factory import MarketFactory

    # Get TradingContext — host apps own session parsing and pass values here
    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )

    # Create optimizer with ctx
    optimizer = OptunaOptimizer(
        ctx=ctx,
        market_adapter=market_adapter,
        strategy_class=strategy_class,
        search_space_fn=optuna_search_space,
    )

    # Run optimization
    study, best_params = optimizer.run(
        indicators=indicators,
        trading_calendar_df=trading_calendar_df,
    )
"""

import pandas as pd
import logging
import optuna
import time
import psutil
from typing import Dict, Any, Tuple, Optional, Union, Callable, TYPE_CHECKING
from functools import partial
from pathlib import Path
from concurrent.futures import (
    ProcessPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
import multiprocessing
from tqdm import tqdm

import sys

from ..engine.optimization_runner import (
    OptimizationRunner,
    OptimizationConfig,
    run_optimization_trial,
)
from ..engine.failure import OptimizationFailure
from .failure_reporter import (
    FailureGroup,
    aggregate as _aggregate_failure,
    render_terminal as _render_failure_terminal,
    write_json_artifact as _write_failure_json,
)
from echolon.backtest.logging_utils import (
    setup_backtest_logging,
    log_workflow_start,
    log_workflow_success,
    log_workflow_failure,
)
from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig

if TYPE_CHECKING:
    from echolon.strategy.interfaces import IMarketAdapter

logger = logging.getLogger(__name__)

# Suppress Optuna's verbose logging during optimization
optuna.logging.set_verbosity(optuna.logging.WARNING)


def _context_spawn_spec(ctx: TradingContext) -> Dict[str, Any]:
    return {
        "market": ctx.market_code,
        "instrument": ctx.instrument_code,
        "frequency": ctx.frequency,
        "bar_size": ctx.bar_size,
        "initial_capital": ctx.initial_capital,
    }


def _spawn_shared_data_payload(shared_data: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(shared_data)
    payload["ctx_spec"] = _context_spawn_spec(shared_data["ctx"])
    market_adapter = shared_data["market_adapter"]
    payload["contract_specs"] = getattr(market_adapter, "_contract_specs", None)
    payload["ctx"] = None
    payload["market_adapter"] = None
    return payload


def _initialize_optimization_worker(shared_data: Dict[str, Any]) -> None:
    """Hydrate worker-local OptimizationRunner shared data under spawn."""
    from echolon.config.markets.factory import MarketFactory
    from echolon.engine.factory import EngineFactory

    ctx_spec = shared_data["ctx_spec"]
    ctx = MarketFactory.create(
        market=ctx_spec["market"],
        instrument=ctx_spec["instrument"],
        frequency=ctx_spec["frequency"],
        bar_size=ctx_spec["bar_size"],
        initial_capital=ctx_spec["initial_capital"],
    )
    market_adapter = EngineFactory.create_market_adapter(
        ctx=ctx,
        mode="backtest",
        market_data_dir=shared_data["market_data_dir"],
    )
    contract_specs = shared_data["contract_specs"]
    if contract_specs is not None:
        market_adapter._contract_specs = dict(contract_specs)

    hydrated = dict(shared_data)
    hydrated["ctx"] = ctx
    hydrated["market_adapter"] = market_adapter
    hydrated.pop("ctx_spec")
    hydrated.pop("contract_specs")
    OptimizationRunner._shared_data = hydrated
    setup_backtest_logging("optimization")


_FIRST_TRIAL_LIVENESS_MESSAGES = (
    "shared data not initialized",
    "indicator_metadata not set",
)


def _is_first_trial_liveness_failure(failure: OptimizationFailure) -> bool:
    if failure.error_type != "PreconditionError":
        return False
    message = failure.message.lower()
    return any(
        expected in message
        for expected in _FIRST_TRIAL_LIVENESS_MESSAGES
    )


# ===============================================================================
# ERROR CLASSIFICATION: WHITELIST APPROACH
# ===============================================================================
# Only these errors are RECOVERABLE (continue optimization).
# All other errors trigger HARD BREAK (stop optimization - strategy needs fixing).

RECOVERABLE_ERRORS_WHITELIST = (
    ZeroDivisionError,      # Division by zero - parameter combination issue
    ValueError,             # Invalid value - parameter range issue
    OverflowError,          # Numerical overflow - parameter too extreme
    FloatingPointError,     # Floating point error - numerical instability
)


def is_recoverable_error(error: Exception) -> bool:
    """
    Check if error is recoverable (parameter issue) or critical (strategy bug).

    Whitelist approach: Only explicitly listed errors are recoverable.
    Everything else (KeyError, AttributeError, etc.) triggers hard break.

    Args:
        error: The exception that occurred during trial

    Returns:
        bool: True if recoverable (continue), False if critical (hard break)
    """
    return isinstance(error, RECOVERABLE_ERRORS_WHITELIST)


def check_for_critical_errors_callback(study: optuna.Study, trial: optuna.trial.FrozenTrial):
    """
    Callback function executed after each trial to check for critical errors.
    If a critical error is detected, stops the study immediately.

    Args:
        study: The Optuna study object
        trial: The completed trial
    """
    if trial.user_attrs.get('CRITICAL_ERROR', False):
        error_type = trial.user_attrs.get('error_type', 'Unknown')
        error_msg = trial.user_attrs.get('error_message', 'Unknown error')
        logger.critical(f"CRITICAL ERROR in trial {trial.number} - STOPPING STUDY IMMEDIATELY")
        study.stop()
        raise RuntimeError(
            f"CRITICAL STRATEGY ERROR in trial {trial.number}: {error_type}: {error_msg}"
        )


def format_time_seconds(seconds: float) -> str:
    """Format seconds into human-readable time string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


class OptunaOptimizer:
    """
    Optuna-based parameter optimizer for trading strategies.

    Parameterized with TradingContext for market-agnostic optimization.
    Uses OptimizationRunner for lightweight backtest execution.

    Parameters
    ----------
    ctx : TradingContext
        Trading context (single source of truth for market/instrument config)
    market_adapter : IMarketAdapter
        Market adapter for market-specific rules
    strategy_class : type
        Backtrader strategy class to optimize
    search_space_fn : Callable
        Function that takes optuna.Trial and returns parameter dict
    n_trials : int
        Number of optimization trials
    optimization_target : str
        Target metric: "sharpe_ratio", "total_return", "multi_objective", etc.
    timeout : int, optional
        Timeout in seconds for optimization
    use_sequential : bool, optional
        Explicit sequential-mode override. When omitted, derives from
        ``optuna_config.n_jobs == 1``.
    run_context : str
        Execution context for logging: "optimization", "debug", "best_trial"
    """

    def __init__(
        self,
        ctx: TradingContext,
        market_adapter: 'IMarketAdapter',
        strategy_class: type,
        search_space_fn: Callable[[optuna.Trial], Dict[str, Any]],
        n_trials: Optional[int] = None,
        optimization_target: Optional[str] = None,
        timeout: Optional[int] = None,
        use_sequential: Optional[bool] = None,
        run_context: str = "optimization",
        optuna_config: Optional[OptunaConfig] = None,
        indicator_dir: Optional[Path] = None,
        paths: Optional["PathsConfig"] = None,  # type: ignore[name-defined]
    ):
        if optuna_config is None:
            raise ValueError(
                "optuna_config is required. Build one with OptunaConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._optuna_config = optuna_config

        self.ctx = ctx
        self.market_adapter = market_adapter
        self.strategy_class = strategy_class
        self.search_space_fn = search_space_fn
        # Explicit constructor arguments override config values (back-compat)
        self.n_trials = n_trials if n_trials is not None else self._optuna_config.n_trials
        self.optimization_target = (
            optimization_target if optimization_target is not None
            else self._optuna_config.target
        )
        self.timeout = timeout if timeout is not None else self._optuna_config.timeout
        self.use_sequential = (
            self._optuna_config.n_jobs == 1
            if use_sequential is None
            else use_sequential
        )
        self.run_context = run_context
        self.start_time: Optional[float] = None

        # Extract from TradingContext
        self.instrument = ctx.instrument_name
        # Resolve `indicator_dir` (the indicators-backtest ROOT) with this
        # priority: explicit kwarg > paths.indicators_backtest_dir >
        # PathsConfig.from_env() (legacy fallback). Store the root and the
        # per-instrument subdir separately so the worker can thread the
        # root into the bridge's strategy params.
        if indicator_dir is None and paths is not None:
            indicator_dir = paths.indicators_backtest_dir
        if indicator_dir is None:
            from echolon.config.paths_config import PathsConfig
            indicator_dir = PathsConfig.from_env().indicators_backtest_dir
        self._indicators_root = str(indicator_dir)
        self.indicators_dir = str(Path(indicator_dir) / ctx.instrument_name)
        # Strategy code dir for the bridge + market_data dir for the SHFE
        # adapter's main_contract.csv resolution. Both forwarded to workers
        # via setup_shared_data so neither needs a from_env() fallback.
        self._strategy_code_dir = (
            str(paths.strategy_code_dir) if paths is not None else None
        )
        self._market_data_dir = (
            str(paths.market_data_dir) if paths is not None else None
        )
        # Note: commission and multiplier are retrieved from market_adapter.get_contract_spec()

        # Controller-side aggregation of per-trial failures. Keyed by
        # OptimizationFailure.group_key(). Populated by _run_parallel /
        # _objective; consumed at end of ``run()`` to render the terminal
        # block and write ``trial_failure_summary.json``.
        self._failure_groups: Dict[tuple, FailureGroup] = {}
        # FLAG-2: collects {trial_number: {date: return}} for per_trial_returns.json.
        # Reset at the start of each run() call (supports multi-window WFA on same instance).
        self._per_trial_returns: Dict[int, Dict[str, float]] = {}

    def run(
        self,
        indicators: pd.DataFrame,
        trading_calendar_df: pd.DataFrame = None,  # noqa: F841 Reserved for session filtering
        segmentation_data: Optional[pd.DataFrame] = None,
        study_name: Optional[str] = None,
        indicator_metadata: Optional[Dict[str, Any]] = None,
        failure_report_dir: Optional[Path] = None,
        failure_report_window_id: Optional[int] = None,
    ) -> Tuple[Optional[optuna.Study], Optional[Dict[str, Any]]]:
        """
        Run optimization study.

        Parameters
        ----------
        indicators : pd.DataFrame
            Market data with indicators (indexed by date)
        trading_calendar_df : pd.DataFrame
            Trading calendar data
        segmentation_data : pd.DataFrame, optional
            Pre-loaded per-bar categorical column for trade-analyzer
            stratification (e.g., TRS-paradigm 'market_regime').
        study_name : str, optional
            Name for the Optuna study
        indicator_metadata : Dict[str, Any], optional
            Indicator metadata dict with 'indicator_columns' key for creating data feed

        Returns
        -------
        Tuple[Optional[optuna.Study], Optional[Dict[str, Any]]]
            The completed study and best parameters (if found)
        """
        # trading_calendar_df reserved for future session filtering
        _ = trading_calendar_df

        # Reset per-run aggregation state. A single OptunaOptimizer instance
        # may drive multiple WFA windows sequentially; each window gets a
        # fresh ``_failure_groups`` so reports don't leak across windows.
        self._failure_groups = {}
        self._per_trial_returns = {}

        # Setup context-aware logging for optimization (suppresses backtest details)
        setup_backtest_logging("optimization")

        # Log workflow start
        log_workflow_start(
            "optimization",
            "OptunaOptimization",
            trials=self.n_trials,
            target=self.optimization_target,
            instrument=self.instrument
        )

        logger.info(f"[{self.run_context.upper()}] Starting optimization | "
                   f"trials={self.n_trials}, target={self.optimization_target}")

        # Setup shared data for child processes via OptimizationRunner
        # Futures components auto-detected from market_adapter.has_contract_expiry
        # Commission and multiplier are retrieved from market_adapter.get_contract_spec()
        opt_config = OptimizationConfig()

        OptimizationRunner.setup_shared_data(
            ctx=self.ctx,
            indicators=indicators,
            market_adapter=self.market_adapter,
            indicators_dir=self.indicators_dir,
            indicators_backtest_dir=self._indicators_root,
            strategy_code_dir=self._strategy_code_dir,
            market_data_dir=self._market_data_dir,
            segmentation_data=segmentation_data,
            optimization_config=opt_config,
            indicator_metadata=indicator_metadata,
        )

        # Pre-load contract prices for O(1) lookups
        if self.indicators_dir:
            logger.info(f"[{self.run_context.upper()}] Pre-loading contract prices...")
            contracts_loaded = OptimizationRunner.preload_contracts(self.indicators_dir)
            logger.info(f"[{self.run_context.upper()}] Loaded {contracts_loaded} contracts")

        study_name = study_name or f"{self.strategy_class.__name__}_optimization"

        # Create sampler
        sampler = optuna.samplers.TPESampler(
            multivariate=True,
            seed=42,
            n_startup_trials=20,
            n_ei_candidates=48
        )

        # Create study
        if self.optimization_target == "multi_objective":
            study = optuna.create_study(
                study_name=study_name,
                storage=None,
                directions=['maximize', 'maximize', 'maximize'],
                sampler=sampler
            )
        else:
            study = optuna.create_study(
                study_name=study_name,
                storage=None,
                direction='maximize',
                sampler=sampler
            )

        self.start_time = time.time()

        if self.use_sequential:
            study = self._run_sequential(study)
        else:
            study = self._run_parallel(study)

        elapsed_time = time.time() - self.start_time
        logger.info(f"[{self.run_context.upper()}] Optimization complete | "
                   f"elapsed={format_time_seconds(elapsed_time)}, "
                   f"trials={len(study.trials)}")

        # Clear shared data after optimization
        OptimizationRunner.clear_shared_data()

        # Get best parameters and log success/failure
        best_params = None
        completed_trials = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
        failed_trials = len([t for t in study.trials if t.state == optuna.trial.TrialState.FAIL])

        if self.optimization_target != "multi_objective" and study.best_trial:
            best_params = study.best_params
            logger.info(f"[{self.run_context.upper()}] Best value: {study.best_value:.4f}")

            # Log SUCCESS marker for debugger_agent
            log_workflow_success(
                "optimization",
                "OptunaOptimization",
                best_value=f"{study.best_value:.4f}",
                completed=completed_trials,
                failed=failed_trials,
                elapsed=format_time_seconds(elapsed_time)
            )
        elif completed_trials == 0:
            # All trials failed - log FAILURE
            log_workflow_failure(
                "optimization",
                "OptunaOptimization",
                f"All {failed_trials} trials failed - check strategy code"
            )
        else:
            # Some trials completed but no best trial (multi-objective)
            log_workflow_success(
                "optimization",
                "OptunaOptimization",
                completed=completed_trials,
                failed=failed_trials,
                elapsed=format_time_seconds(elapsed_time)
            )

        # Failure reporting — always render a stderr block when any trial
        # failed (making silent failures impossible), and persist the
        # JSON artifact when a target directory was provided.
        if failed_trials > 0 and self._failure_groups:
            summary = _render_failure_terminal(
                n_trials=self.n_trials,
                n_failed=failed_trials,
                groups=self._failure_groups.values(),
                window_id=failure_report_window_id,
            )
            print(summary, file=sys.stderr)
        if failure_report_dir is not None:
            _write_failure_json(
                out_path=Path(failure_report_dir) / "trial_failure_summary.json",
                n_trials=self.n_trials,
                n_failed=failed_trials,
                n_complete=completed_trials,
                groups=self._failure_groups.values(),
                window_id=failure_report_window_id,
            )

        return study, best_params

    def _run_sequential(self, study: optuna.Study) -> optuna.Study:
        """Run optimization sequentially (for debugging)."""
        logger.warning("=" * 80)
        logger.warning("RUNNING IN SEQUENTIAL MODE (n_jobs=1) FOR DEBUGGING")
        logger.warning("=" * 80)

        objective_func = partial(
            self._objective,
            _base_params={}  # No longer used, kept for API compatibility
        )

        study.optimize(
            objective_func,
            n_trials=self.n_trials,
            n_jobs=1,
            timeout=self.timeout,
            catch=RECOVERABLE_ERRORS_WHITELIST,
            callbacks=[check_for_critical_errors_callback],
            gc_after_trial=True,
            show_progress_bar=True
        )

        return study

    def _run_parallel(self, study: optuna.Study) -> optuna.Study:
        """Run optimization with process-based parallelization."""
        worker_config = self._get_optimal_worker_configuration()
        max_workers = worker_config['max_workers']

        print(f"[OPTUNA] Starting optimization | trials={self.n_trials}, workers={max_workers}")

        completed_trials = 0
        failed_trials = 0
        batch_size = max_workers

        # Progress bar with ETA.
        # Throttled to keep logs readable when stdout isn't a live TTY
        # (captured logs, piped runs, CI). ``mininterval=0.5`` caps render
        # rate at 2/sec; ``miniters`` ensures we don't render every trial
        # on fast studies. ``dynamic_ncols`` lets tqdm honor the current
        # terminal width instead of the old hardcoded ``ncols=100``.
        pbar = tqdm(
            total=self.n_trials,
            desc="Optimization",
            unit="trial",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
            mininterval=0.5,
            miniters=max(1, self.n_trials // 50),
            dynamic_ncols=True,
        )

        while completed_trials < self.n_trials:
            remaining = self.n_trials - completed_trials
            current_batch = min(batch_size, remaining)

            # Generate trial suggestions from Optuna
            trials_to_run = []
            for _ in range(current_batch):
                trial = study.ask()
                trial_params = self.search_space_fn(trial)
                trials_to_run.append((trial, trial_params))

            # Execute batch in parallel. Use module-level functions and a
            # spawn initializer: workers start from a clean interpreter and
            # hydrate OptimizationRunner._shared_data explicitly instead of
            # inheriting it from a threaded parent process via fork.
            shared_data = _spawn_shared_data_payload(OptimizationRunner._shared_data)
            with ProcessPoolExecutor(
                max_workers=min(current_batch, max_workers),
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialize_optimization_worker,
                initargs=(shared_data,),
            ) as executor:
                future_to_trial = {
                    executor.submit(
                        run_optimization_trial,
                        trial_params,
                        trial.number
                    ): trial
                    for trial, trial_params in trials_to_run
                }

                try:
                    completed_futures = as_completed(
                        future_to_trial,
                        timeout=self.timeout,
                    )
                    for future in completed_futures:
                        trial = future_to_trial[future]
                        try:
                            result = future.result()
                            if result['success']:
                                if self.optimization_target == "multi_objective":
                                    study.tell(trial, result['values'])
                                else:
                                    study.tell(trial, result['value'])
                                # FLAG-2: collect per-trial daily returns from IPC dict
                                _dr = result.get('metrics', {}).get('daily_returns')
                                if _dr:
                                    self._per_trial_returns[trial.number] = _dr
                            else:
                                study.tell(trial, state=optuna.trial.TrialState.FAIL)
                                failed_trials += 1
                                # Aggregate structured failure for end-of-study
                                # reporting. ``failure`` is the dict form of
                                # OptimizationFailure — reconstruct and fold in.
                                failure_dict = result.get('failure')
                                if failure_dict is not None:
                                    failure = OptimizationFailure(**failure_dict)
                                    if (
                                        completed_trials == 0
                                        and pbar.n == 0
                                        and _is_first_trial_liveness_failure(failure)
                                    ):
                                        pbar.close()
                                        raise RuntimeError(
                                            "CRITICAL first trial liveness failure: "
                                            f"{failure.message}"
                                        )
                                    _aggregate_failure(
                                        self._failure_groups, failure, trial.number,
                                    )
                                if result.get('critical_error'):
                                    pbar.close()
                                    # Print critical error directly to terminal
                                    failure_repr = result.get('failure') or {}
                                    err_msg = failure_repr.get('message', 'Unknown error')
                                    print(f"\n{'='*60}")
                                    print(f"CRITICAL ERROR in trial {trial.number}")
                                    print(f"Error: {err_msg}")
                                    print(f"{'='*60}\n")
                                    raise RuntimeError(err_msg)
                        except Exception as e:
                            if "CRITICAL" in str(e):
                                pbar.close()
                                raise
                            failed_trials += 1
                            study.tell(trial, state=optuna.trial.TrialState.FAIL)

                        # Update progress bar — postfix without ``refresh=True``
                        # so tqdm batches the redraw with the throttled update
                        # cycle instead of forcing one render per trial.
                        pbar.update(1)
                        pbar.set_postfix({'failed': failed_trials})
                except FuturesTimeoutError as exc:
                    for pending in future_to_trial:
                        pending.cancel()
                    pbar.close()
                    raise TimeoutError(
                        "Optimization batch timed out after "
                        f"{self.timeout}s with {len(future_to_trial)} trial(s) "
                        "still outstanding"
                    ) from exc

            completed_trials += current_batch

        pbar.close()
        print(f"[OPTUNA] Complete | trials={completed_trials}, failed={failed_trials}")
        return study

    def _objective(
        self,
        trial: optuna.Trial,
        _base_params: Dict[str, Any]  # Kept for compatibility with partial()
    ) -> Union[float, Tuple[float, float, float]]:
        """
        Optuna objective function that runs a backtest with trial parameters.

        Uses OptimizationRunner for lightweight backtest execution.

        Args:
            trial: Optuna trial object
            _base_params: Unused, kept for compatibility with partial()

        Returns:
            Objective value(s) to optimize
        """
        trial_id = trial.number

        # Generate trial parameters
        trial_params = self.search_space_fn(trial)

        # Run backtest via OptimizationRunner
        metrics = OptimizationRunner.run_trial(trial_params, trial_id)

        if not metrics.success:
            error_msg = metrics.error_message or "Unknown error"
            # Sequential path aggregates failures directly (no result dict).
            if metrics.failure is not None:
                _aggregate_failure(self._failure_groups, metrics.failure, trial_id)
            if is_recoverable_error(Exception(error_msg)):
                logger.warning(f"[{self.run_context.upper()}] Trial {trial_id} | "
                             f"RECOVERABLE: {error_msg}")
            else:
                logger.critical("=" * 80)
                logger.critical(f"CRITICAL ERROR in trial {trial_id}")
                logger.critical(f"Error: {error_msg}")
                logger.critical("=" * 80)
                trial.set_user_attr('CRITICAL_ERROR', True)
                trial.set_user_attr('error_type', 'BacktestError')
                trial.set_user_attr('error_message', error_msg)
                raise RuntimeError(f"CRITICAL: {error_msg}")

            if self.optimization_target == "multi_objective":
                return (-1.0, -999.0, -100.0)
            return -1.0

        # Store metrics for analysis
        trial.set_user_attr('sharpe_ratio', metrics.sharpe_ratio)
        trial.set_user_attr('max_drawdown_pct', metrics.max_drawdown_pct)
        trial.set_user_attr('annual_return_pct', metrics.annual_return_pct)
        trial.set_user_attr('total_trades', metrics.total_trades)

        # FLAG-2: capture per-trial daily returns
        if metrics.daily_returns:
            self._per_trial_returns[trial_id] = metrics.daily_returns

        # Return based on target
        if self.optimization_target == "multi_objective":
            return metrics.get_multi_objective_values()
        else:
            return metrics.get_single_objective_value(self.optimization_target)

    # NOTE: _run_trial_in_process method was removed.
    # Reason: Bound methods require pickling 'self', which contains ctx (TradingContext)
    # with unpicklable lambda functions. The fix was to use the module-level
    # run_optimization_trial() function directly in ProcessPoolExecutor.submit().

    def _get_optimal_worker_configuration(self) -> Dict[str, int]:
        """Determine optimal worker configuration based on system resources."""
        cpu_count = psutil.cpu_count(logical=True)
        memory_gb = psutil.virtual_memory().total / (1024**3)

        # Conservative approach: leave some CPUs for system
        max_workers = max(1, min(cpu_count - 4, 44))

        # Memory-limited workers
        estimated_memory_per_worker = 0.5  # GB
        memory_limited_workers = int(memory_gb * 0.8 / estimated_memory_per_worker)

        optimal_workers = min(max_workers, memory_limited_workers)
        batch_size = max(8, optimal_workers // 4)

        logger.info(f"System: {cpu_count} CPUs, {memory_gb:.1f}GB RAM")
        logger.info(f"Config: {optimal_workers} workers, batch size {batch_size}")

        return {
            'max_workers': optimal_workers,
            'batch_size': batch_size,
            'cpu_count': cpu_count
        }

    def save_study_results(
        self,
        study: optuna.Study,
        output_dir: str,
        save_trials_csv: bool = True,
        save_best_params: bool = True,
    ) -> None:
        """
        Save optimization results to disk.

        Parameters
        ----------
        study : optuna.Study
            Completed Optuna study
        output_dir : str
            Directory to save results
        save_trials_csv : bool
            Whether to save all trials to CSV
        save_best_params : bool
            Whether to save best parameters to JSON
        """
        import json
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if save_trials_csv:
            trials_df = study.trials_dataframe()
            trials_path = output_path / "optimization_trials.csv"
            trials_df.to_csv(trials_path, index=False)
            logger.info(f"Saved trials to {trials_path}")

        # FLAG-2: per-trial daily returns export
        # Shape: {trial_number_str: {date_str: return_float}}
        # Only successful trials with returns data; honest skipped_trials list.
        # Size note: 50 trials × ~4k days ≈ few MB.
        if self._per_trial_returns:
            completed_nums = {
                t.number
                for t in study.trials
                if t.state == optuna.trial.TrialState.COMPLETE
            }
            skipped = sorted(completed_nums - set(self._per_trial_returns.keys()))
            per_trial_payload = {
                'per_trial_returns': {
                    str(k): v for k, v in sorted(self._per_trial_returns.items())
                },
                'skipped_trials': skipped,
            }
            ptr_path = output_path / 'per_trial_returns.json'
            with open(ptr_path, 'w') as f:
                json.dump(per_trial_payload, f, indent=2)
            logger.info(f"Saved per-trial returns to {ptr_path}")

        if save_best_params and self.optimization_target != "multi_objective":
            if study.best_trial:
                best_params = {
                    'trial_number': study.best_trial.number,
                    'best_value': study.best_value,
                    'params': study.best_params,
                    'user_attrs': study.best_trial.user_attrs,
                }
                params_path = output_path / "best_params.json"
                with open(params_path, 'w') as f:
                    json.dump(best_params, f, indent=2, default=str)
                logger.info(f"Saved best params to {params_path}")


# =============================================================================
# BT-003 helper: raise EchelonError on Optuna hard-constraint violation
# =============================================================================

from echolon.errors import raise_error


def _raise_constraint_violation(
    trial_number: int,
    constraint: str,
    required,
    actual,
    params: dict,
) -> None:
    """Raise BT-003 with Optuna trial params in context. Callers should invoke
    this when a hard constraint fails, so the exception's structured context
    (trial_number, constraint, required, actual, params) is captured even if
    the trial's score is also clamped to 0 for Optuna's convergence logic."""
    raise_error(
        "BT-003",
        trial_number=trial_number,
        constraint=constraint,
        required=required,
        actual=actual,
        params=params,
    )
