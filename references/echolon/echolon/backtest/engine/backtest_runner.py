"""
Backtest Runner
===============

High-level orchestrator for running single backtests with full features.

Used for:
- Debug mode: Quick iteration with DEFAULT_PARAMS
- Best Trial mode: Run with optimized parameters

Features:
- Full CSV strategy logging
- Result saving (JSON, trades CSV, equity curve)
- Detailed metrics collection
- Contract-aware broker for futures

For optimization (many parallel runs), use OptimizationRunner instead.

Usage:
    from echolon.config.markets.factory import MarketFactory

    # Get TradingContext — host apps own session parsing and pass values here
    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )

    # Debug backtest
    results = BacktestRunner.debug(ctx)

    # Best trial backtest
    results = BacktestRunner.best_trial(ctx)

    # Custom parameters
    runner = BacktestRunner(ctx)
    runner.load_data()
    results = runner.run(params=my_params, context='custom')
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

from .backtrader_engine import BacktestResults
from .enriched_pandas_data import EnrichedPandasData
from echolon.engine.factory import EngineFactory
from echolon.backtest.metrics.reporting import convert_to_serializable, save_trade_log, save_equity_curve
from echolon.data.loaders.backtest_data_loader import load_backtest_data, load_indicator_metadata, load_best_params


def _get_default_params(strategy_code_dir: Path):
    """Lazy load DEFAULT_PARAMS from the strategy code dir."""
    from echolon.strategy.loader import StrategyLoader
    loader = StrategyLoader(Path(strategy_code_dir))
    return loader.load_attr("strategy_params", "DEFAULT_PARAMS")


from echolon.backtest.metrics.mfe_mae import enrich_trades_with_mfe_mae
from echolon.backtest.schemas import BacktestResultsSchemaV4
from .backtrader_strategy import get_strategy_class
from echolon.config.markets.core.context import TradingContext
from echolon.config.backtest_config import BacktestConfig
from echolon.backtest.logging_utils import (
    setup_backtest_logging,
    log_workflow_start,
    log_workflow_success,
    log_workflow_failure,
    log_result_summary,
    log_zero_trades_warning,
    get_run_context,
)

logger = logging.getLogger(__name__)

_OPTIONAL_SERIES_ARTIFACTS = ("backtest_trades.csv", "equity_curve.csv")


def unlink_optional_series_artifacts(output_dir: Path) -> None:
    """Remove optional per-run series before saving a fresh result."""
    for name in _OPTIONAL_SERIES_ARTIFACTS:
        path = Path(output_dir) / name
        if path.exists():
            path.unlink()


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class _RunnerConfig:
    """Internal runner options (paths + feature flags).

    Not part of the public API — use the Pydantic ``BacktestConfig`` from
    ``echolon.config.backtest_config`` for external configuration.

    Path fields default to ``None``; ``BacktestRunner.__init__`` populates
    any unset ones from its required ``paths=`` kwarg. No env / cwd fallback.
    """
    # Paths — None at construction is allowed (so callers can build
    # _RunnerConfig() then mutate selected fields); BacktestRunner.__init__
    # then fills any unset fields from its required ``paths=`` kwarg.
    indicator_dir: Optional[str] = None  # workspace/data/indicators/backtest/
    market_data_dir: Optional[str] = None  # workspace/data/market_data/
    backtest_results_dir: Optional[str] = None  # workspace/backtest/  (host apps may override)

    # Features
    enable_strategy_logging: bool = True


# =============================================================================
# BacktestRunner Class
# =============================================================================

class BacktestRunner:
    """
    Full-featured backtest runner for single runs.

    Handles data loading, engine creation, backtest execution,
    and result saving. Optimized for debug and best_trial modes.

    For optimization (parallel runs), use OptimizationRunner instead.

    Parameters
    ----------
    ctx : TradingContext
        Trading context with market, instrument, and frequency configuration.
        This is the single source of truth for all trading parameters.
    config : _RunnerConfig, optional
        Internal runner options (paths + feature flags). Uses defaults if None.
    """

    def __init__(self, ctx: TradingContext,
                 *,
                 paths: "PathsConfig",  # type: ignore[name-defined]
                 config: Optional[_RunnerConfig] = None,
                 strategy_code_dir: Optional[str] = None,
                 backtest_config: Optional[BacktestConfig] = None):
        """
        Initialize BacktestRunner with TradingContext.

        Args:
            ctx: TradingContext containing market, instrument, frequency info
            paths: Required PathsConfig. Used to fill any _RunnerConfig path
                fields the caller didn't pre-populate. No from_env() fallback.
            config: Optional _RunnerConfig. Path fields default to the
                corresponding paths.* values; caller can override per-field
                before constructing the runner.
            strategy_code_dir: Optional path to strategy code directory.
                If provided, strategy is loaded from this directory via importlib
                instead of from ``paths.strategy_code_dir``. Used by portfolio
                backtest to run per-slot strategies.
            backtest_config: Pydantic ``BacktestConfig`` providing date
                ranges, data paths, and drawdown thresholds.  Required.
        """
        if backtest_config is None:
            raise ValueError(
                "backtest_config is required. Build one with BacktestConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._backtest_config = backtest_config

        self.ctx = ctx
        self._paths = paths
        self.config = config or _RunnerConfig()
        # Fill path fields from paths= for any field the caller left unset.
        # No from_env() fallback — paths is required and authoritative.
        if self.config.indicator_dir is None:
            self.config.indicator_dir = str(paths.indicators_backtest_dir)
        if self.config.market_data_dir is None:
            self.config.market_data_dir = str(paths.market_data_dir)
        if self.config.backtest_results_dir is None:
            self.config.backtest_results_dir = str(paths.backtest_results_dir)
        # Default strategy_code_dir to paths.strategy_code_dir when caller
        # didn't specify a slot — avoids the bridge's PathsConfig.from_env()
        # fallback (which would silently resolve to OSS defaults relative to
        # cwd / ECHOLON_PROJECT_ROOT, not the host app's overridden layout).
        self.strategy_code_dir = (
            strategy_code_dir if strategy_code_dir is not None
            else str(paths.strategy_code_dir)
        )

        # State
        self._indicators: Optional[pd.DataFrame] = None
        self._trading_calendar: Optional[pd.DataFrame] = None
        self._metadata: Optional[Dict[str, Any]] = None
        self._data_loaded = False

    # =========================================================================
    # Properties for convenient access
    # =========================================================================

    @property
    def market(self) -> str:
        """Market code (e.g., 'SHFE', 'CRYPTO')."""
        return self.ctx.market_code

    @property
    def instrument(self) -> str:
        """Instrument name (e.g., 'aluminum', 'bitcoin')."""
        return self.ctx.instrument_name

    @property
    def instrument_code(self) -> str:
        """Instrument code (e.g., 'al', 'btc')."""
        return self.ctx.instrument_code

    # =========================================================================
    # Data Loading
    # =========================================================================

    def load_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> 'BacktestRunner':
        """
        Load indicators and trading calendar using shared data loader utilities.

        Parameters
        ----------
        start_date : str, optional
            Override config start date
        end_date : str, optional
            Override config end date

        Returns
        -------
        BacktestRunner
            Self for method chaining
        """
        start_date = start_date or self._backtest_config.start_date
        end_date = end_date or self._backtest_config.end_date

        # Load data — per-slot dir if strategy_code_dir set, else default.
        # Forward self.config.market_data_dir + indicator_dir explicitly so
        # the loader honors workspace-local overrides.
        market_data_dir = Path(self.config.market_data_dir)
        indicator_dir = Path(self.config.indicator_dir)
        if self.strategy_code_dir:
            slot_name = Path(self.strategy_code_dir).name
            slot_ind_dir = indicator_dir / slot_name
            slot_csv = slot_ind_dir / "strategy_indicators.csv"
            if slot_csv.exists():
                self._indicators, self._trading_calendar = load_backtest_data(
                    ctx=self.ctx,
                    indicators_path=str(slot_csv),
                    market_data_dir=market_data_dir,
                )
            else:
                # Fallback to {indicator_dir}/{instrument}/strategy_indicators.csv
                self._indicators, self._trading_calendar = load_backtest_data(
                    ctx=self.ctx,
                    indicator_dir=indicator_dir,
                    market_data_dir=market_data_dir,
                )
        else:
            self._indicators, self._trading_calendar = load_backtest_data(
                ctx=self.ctx,
                indicator_dir=indicator_dir,
                market_data_dir=market_data_dir,
            )

        # Sort index for proper slicing (intraday data has non-unique dates)
        self._indicators = self._indicators.sort_index()

        # Filter to backtest period using boolean indexing for non-monotonic index
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        self._indicators = self._indicators[
            (self._indicators.index >= start_ts) & (self._indicators.index <= end_ts)
        ].copy()

        if self._indicators.empty:
            raise ValueError(f"No data for period {start_date} to {end_date}")

        # Load metadata — per-slot dir if strategy_code_dir set, else default.
        # Forward indicator_dir explicitly so the loader doesn't fall back to
        # PathsConfig.from_env() (which is now forbidden in library code).
        if self.strategy_code_dir:
            slot_name = Path(self.strategy_code_dir).name
            slot_meta = indicator_dir / slot_name / "strategy_indicator_metadata.json"
            if slot_meta.exists():
                self._metadata = load_indicator_metadata(ctx=self.ctx, metadata_path=str(slot_meta))
            else:
                self._metadata = load_indicator_metadata(ctx=self.ctx, indicator_dir=indicator_dir)
        else:
            self._metadata = load_indicator_metadata(ctx=self.ctx, indicator_dir=indicator_dir)

        self._data_loaded = True

        logger.info(
            f"[BACKTEST_RUNNER] Data loaded | "
            f"rows={len(self._indicators)}, period={start_date} to {end_date}"
        )

        return self

    # =========================================================================
    # Backtest Execution
    # =========================================================================

    def run(
        self,
        params: Dict[str, Any],
        context: str = 'debug',
        save_results: bool = True,
    ) -> Dict[str, Any]:
        """
        Run backtest with provided parameters.

        Parameters
        ----------
        params : Dict[str, Any]
            Strategy parameters
        context : str
            Run context: 'debug', 'best_trial', 'custom'
        save_results : bool
            Whether to save results to files

        Returns
        -------
        Dict[str, Any]
            Detailed results dictionary
        """
        if not self._data_loaded:
            self.load_data()

        # Setup context-aware logging. Pass canonical RunContext values
        # straight through; fall back to "best_trial" for non-canonical
        # callers (legacy 'custom', 'manual', 'backtest' from public API).
        if context in ("optimization", "summary", "debug", "best_trial"):
            run_context = context
        else:
            run_context = "best_trial"
        setup_backtest_logging(run_context)

        # Log workflow start
        log_workflow_start(
            context=run_context,
            workflow="Backtest",
            market=self.market,
            instrument=self.instrument,
            bars=len(self._indicators),
        )

        # Setup paths
        output_dir = Path(self.config.backtest_results_dir)
        # Indicator directory for contract-aware broker. Two valid layouts:
        #   slot-style:       {indicator_dir}/{slot_name}/by_contract/
        #   instrument-style: {indicator_dir}/{instrument}/by_contract/
        # `slot_name` is the basename of strategy_code_dir (always set —
        # defaults to paths.strategy_code_dir at __init__). Probe the
        # slot-style layout first; fall back to instrument-style if that
        # subdir doesn't exist. Mirrors the same existence-check fallback
        # that load_data() applies for strategy_indicators.csv.
        root = Path(self.config.indicator_dir)
        slot_name = Path(self.strategy_code_dir).name
        slot_dir = root / slot_name
        if (slot_dir / "by_contract").is_dir():
            indicator_dir = str(slot_dir)
        else:
            indicator_dir = str(root / self.instrument)

        # Strategy logging directory
        strategy_log_dir = None
        if self.config.enable_strategy_logging:
            strategy_log_dir = str(output_dir / f"strategy_logs_{context}")
            os.makedirs(strategy_log_dir, exist_ok=True)

        # Create engine using factory with TradingContext.
        # market_data_dir is forwarded to the market adapter so
        # adapter.get_main_contract resolves main_contract.csv at the
        # conventional {market_data_dir}/SHFE/{instrument_name}/ path.
        engine = EngineFactory.create_backtest_engine(
            ctx=self.ctx,
            indicators_dir=indicator_dir,
            strategy_logger_enabled=self.config.enable_strategy_logging,
            strategy_logger_dir=strategy_log_dir,
            market_data_dir=Path(self.config.market_data_dir),
        )

        # Create data feed class from metadata, then instantiate
        DataFeedClass = EnrichedPandasData.from_metadata(self._metadata)
        data_feed = DataFeedClass(dataname=self._indicators)

        # Get strategy class using ctx; pass indicators_backtest_dir so the
        # bridge resolves per-slot metadata under the workspace-local override.
        strategy_class = get_strategy_class(
            ctx=self.ctx,
            strategy_code_dir=self.strategy_code_dir,
            indicators_backtest_dir=self.config.indicator_dir,
        )

        # Extract segmentation data for trade analyzers (BUG_001 attribution fix).
        # TRS-paradigm strategies use 'market_regime' as the segmentation column;
        # other paradigms can stratify analyzers by their own categorical column.
        segmentation_data = None
        if 'market_regime' in self._indicators.columns:
            segmentation_data = self._indicators[['market_regime']].reset_index()
            segmentation_data.columns = ['trading_date', 'market_regime']
            logger.debug(f"Segmentation data extracted for analyzers: {len(segmentation_data)} records")

        # Setup and run (commission, slippage, multiplier auto-retrieved from market_adapter)
        engine.setup(
            data_feed=data_feed,
            strategy_class=strategy_class,
            strategy_params=params,
            segmentation_data=segmentation_data,  # BUG_001 fix: pass segmentation data to analyzers
        )

        results = engine.run()

        # Build detailed results
        detailed_results = self._build_results(results, strategy_log_dir)

        # Log summary
        self._log_summary(results, context)

        # Save results
        if save_results:
            self._save_results(detailed_results, params, context, output_dir)

        return detailed_results

    def _build_results(
        self,
        results: BacktestResults,
        strategy_log_dir: Optional[str],
    ) -> Dict[str, Any]:
        """Build detailed results dictionary with MFE/MAE enrichment."""
        detailed = {
            'sharpe_ratio_annual': results.sharpe_ratio,
            'total_return_pct': results.total_return,
            'max_drawdown_pct': results.max_drawdown,
            'total_trades': results.total_trades,
            'winning_trades': results.winning_trades,
            'losing_trades': results.losing_trades,
            'win_rate_pct': (
                results.winning_trades / results.total_trades * 100
                if results.total_trades > 0 else 0
            ),
            'initial_value': results.initial_value,
            'final_value': results.final_value,
        }

        # Add analyzer results (includes trades and equity_curve)
        detailed.update(results.analyzers)

        # Enrich trades with MFE/MAE metrics for exit quality analysis
        # This enables downstream ExitEffectivenessAnalyzer to work
        if 'trades' in detailed and detailed['trades']:
            trades_list = detailed['trades']
            if isinstance(trades_list, dict) and 'trades' in trades_list:
                # Handle wrapped format: {'trades': [...]}
                enriched = enrich_trades_with_mfe_mae(
                    trades_list=trades_list['trades'],
                    ctx=self.ctx,
                    paths=self._paths,
                )
                detailed['trades'] = {'trades': enriched}
            elif isinstance(trades_list, list):
                # Handle direct list format
                enriched = enrich_trades_with_mfe_mae(
                    trades_list=trades_list,
                    ctx=self.ctx,
                    paths=self._paths,
                )
                detailed['trades'] = enriched

        # Add log directory
        if strategy_log_dir:
            detailed['strategy_log_dir'] = strategy_log_dir

        return detailed

    def _log_summary(self, results: BacktestResults, context: str) -> None:
        """Log results summary with SUCCESS/FAILURE markers."""
        run_context = get_run_context()

        # Check for zero trades - critical diagnostic (BT-002)
        # _assert_trades_produced logs the diagnostic warning and raises
        # an EchelonError so callers (and LLM log readers) see a structured code.
        _assert_trades_produced(
            total_trades=results.total_trades,
            bars_processed=len(self._indicators),
            entry_signals_generated=0,  # Would need strategy stats
            entry_signals_blocked=0,
            risk_blocks=0,
        )

        # Log result summary (CRITICAL level for debugger_agent)
        win_rate = (
            results.winning_trades / results.total_trades * 100
            if results.total_trades > 0 else 0
        )
        log_result_summary(
            run_context,
            "Backtest",
            sharpe=results.sharpe_ratio or 0,
            total_return=results.total_return or 0,
            max_drawdown=results.max_drawdown or 0,
            num_trades=results.total_trades,
            win_rate=win_rate,
        )

        # Log SUCCESS marker
        log_workflow_success(
            run_context,
            "Backtest",
            sharpe=f"{results.sharpe_ratio:.3f}" if results.sharpe_ratio else "N/A",
            total_return=f"{results.total_return:.2f}%",
            trades=results.total_trades,
        )

        # Also log at INFO level for compatibility
        sharpe = f"{results.sharpe_ratio:.3f}" if results.sharpe_ratio else "N/A"
        max_dd = f"{results.max_drawdown:.2f}%" if results.max_drawdown else "N/A"

        logger.info(
            f"[BACKTEST_RUNNER] Complete | context={context}, "
            f"sharpe={sharpe}, return={results.total_return:.2f}%, "
            f"max_dd={max_dd}, trades={results.total_trades}"
        )

    def _save_results(
        self,
        results: Dict[str, Any],
        params: Dict[str, Any],
        context: str,
        output_dir: Path,
    ) -> None:
        """Save results to files using reporting utilities."""
        os.makedirs(output_dir, exist_ok=True)

        # Build results data structure
        results_data = {
            "schema_version": "4.0",
            "run_timestamp": datetime.now().isoformat(),
            "run_context": context,
            "market": self.market,
            "instrument": self.instrument,
            "instrument_code": self.instrument_code,
            "performance_metrics": convert_to_serializable({
                k: v for k, v in results.items()
                if k not in ['trades', 'equity_curve', 'strategy_log_dir']
            }),
            "strategy_parameters": convert_to_serializable(params),
        }

        # Validate against schema before saving (fail-fast)
        validated = BacktestResultsSchemaV4.model_validate(results_data)
        logger.info(f"[BACKTEST_RUNNER] Schema validated | version={validated.schema_version}")

        results_path = output_dir / "backtest_results.json"
        with open(results_path, 'w') as f:
            json.dump(validated.model_dump(), f, indent=4, default=str)

        logger.info(f"[BACKTEST_RUNNER] Results saved | path={results_path}")

        unlink_optional_series_artifacts(output_dir)

        # Save trade log using reporting utility
        if 'trades' in results and results['trades']:
            trades_path = str(output_dir / "backtest_trades.csv")
            save_trade_log(results['trades'], trades_path)

        # Save equity curve using reporting utility
        if 'equity_curve' in results and results['equity_curve']:
            equity_path = str(output_dir / "equity_curve.csv")
            save_equity_curve(results['equity_curve'], equity_path)

    # =========================================================================
    # Convenience Class Methods
    # =========================================================================

    @classmethod
    def debug(
        cls,
        ctx: TradingContext,
        backtest_config: Optional[BacktestConfig] = None,
        *,
        paths: "PathsConfig",  # type: ignore[name-defined]
    ) -> Dict[str, Any]:
        """
        Run debug backtest with DEFAULT_PARAMS.

        Convenience method for quick strategy iteration.

        Parameters
        ----------
        ctx : TradingContext
        backtest_config : BacktestConfig
        paths : PathsConfig (required, keyword-only)
        """
        runner = cls(ctx, paths=paths, backtest_config=backtest_config)
        runner.load_data()
        return runner.run(
            _get_default_params(paths.strategy_code_dir),
            context='debug',
        )

    @classmethod
    def best_trial(
        cls,
        ctx: TradingContext,
        params_path: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        strategy_code_dir: Optional[str] = None,
        backtest_config: Optional[BacktestConfig] = None,
        *,
        paths: "PathsConfig",  # type: ignore[name-defined]
        results_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run backtest with best parameters from optimization.

        Loads parameters from selected_robust_trial.json.

        Parameters
        ----------
        ctx : TradingContext
            Trading context (single source of truth)
        params_path : str, optional
            Path to parameters JSON. Uses default if None.
        start_date : str, optional
            Override backtest start date (e.g. OOS_START_DATE for out-of-sample).
        end_date : str, optional
            Override backtest end date (e.g. OOS_END_DATE for out-of-sample).
        strategy_code_dir : str, optional
            Path to strategy code directory. If provided, loads strategy
            from this directory instead of platform_agnostic/.
        backtest_config : BacktestConfig, optional
            Pydantic config with date ranges, paths, and thresholds.
            Falls back to module globals if not provided.
        results_dir : str, optional
            Override the output directory for ALL persisted artifacts —
            backtest_results.json / equity_curve.csv / backtest_trades.csv AND the
            per-bar strategy log (``strategy_logs_{context}/``), which all write under
            this one dir. Default None → ``paths.backtest_results_dir`` (the canonical
            ``workspace/current/backtest/``). Point a READ-ONLY probe (e.g. a windowed
            live-fidelity replay) at a SEPARATE subdir so its windowed artifacts are
            preserved for inspection WITHOUT clobbering the canonical full-backtest
            files the analysis layer + evaluation read.

        Returns
        -------
        Dict[str, Any]
            Detailed results
        """
        runner = cls(
            ctx,
            paths=paths,
            strategy_code_dir=strategy_code_dir,
            backtest_config=backtest_config,
            config=_RunnerConfig(backtest_results_dir=results_dir),
        )

        # Default params path — from slot dir if provided, else from paths.
        if params_path is None:
            if strategy_code_dir:
                params_path = str(Path(strategy_code_dir) / "selected_robust_trial.json")
            else:
                params_path = str(paths.best_params_file)

        # Load the recorded flat optuna params.
        params_data = load_best_params(params_path)
        optuna_params = params_data.get('params', params_data)

        # Resolve to the optimizer-exact nested component vector. AUTHORITATIVE
        # sources ONLY — the lossy strip-once flat-name mapping was removed.
        strategy_params = cls._resolve_optimized_params(
            params_path,
            optuna_params,
            strategy_code_dir=(strategy_code_dir or str(paths.strategy_code_dir)),
        )

        return runner.load_data(start_date=start_date, end_date=end_date).run(
            strategy_params, context='best_trial'
        )

    @classmethod
    def _resolve_optimized_params(
        cls,
        params_path: str,
        optuna_params: Dict[str, Any],
        *,
        strategy_code_dir: str,
    ) -> Dict[str, Any]:
        """Resolve the optimizer-exact nested component vector, or HARD-FAIL.

        Two AUTHORITATIVE sources, in order — there is NO lossy flat-name
        fallback (the historical strip-once mapper silently orphaned
        prefixed-canonical params and dropped in-function shared copies; it was
        deleted):

          1. ``resolved_params.json`` companion, sha-verified against the trial
             file just loaded (provenance fast-path).
          2. On-demand replay of the dir's OWN ``optuna_search_space`` — the
             same computation the exporter runs, so it reproduces the artifact
             byte-for-byte. This means an artifact-less dir (a pre-fix archive,
             a deployed slot) still resolves to the correct vector with NO
             backfill.

        If neither yields a vector, raise **PRM-005** rather than backtest on
        partially-correct parameters — a hard failure beats a silent flaw.
        """
        resolved = cls._resolved_strategy_params(params_path, optuna_params)
        if resolved is not None:
            return resolved
        replayed = cls._replay_strategy_params(
            optuna_params, strategy_code_dir=strategy_code_dir
        )
        if replayed is not None:
            return replayed
        raise_error(
            "PRM-005",
            params_path=str(params_path),
            strategy_code_dir=str(strategy_code_dir),
        )

    @staticmethod
    def _replay_strategy_params(
        optuna_params: Dict[str, Any],
        *,
        strategy_code_dir: str,
    ) -> Optional[Dict[str, Any]]:
        """Recompute the optimizer-exact nested vector by replaying the dir's
        own ``optuna_search_space`` with the recorded flat params.

        This is the SAME ``resolve_via_replay`` the TrialSelector exporter runs,
        so the result is byte-identical to a ``resolved_params.json`` artifact —
        it is authoritative, not a degraded fallback. Returns None (logged) when
        the search space can't be loaded or the replay can't run; the caller
        then hard-fails (PRM-005) rather than guess.
        """
        try:
            from echolon.strategy.loader import StrategyLoader
            from echolon._internal.param_resolution import resolve_via_replay

            search_space_fn = StrategyLoader(Path(strategy_code_dir)).load_attr(
                "strategy_params", "optuna_search_space"
            )
            nested = resolve_via_replay(search_space_fn, optuna_params)
            if nested is None:
                return None
            logger.info(
                "[BEST_TRIAL] params source: on-demand replay of "
                "optuna_search_space (no resolved_params.json artifact present)"
            )
            return {
                key: dict(value)
                for key, value in nested.items()
                if isinstance(value, dict)
            }
        except Exception as exc:  # noqa: BLE001 — any load/replay failure → caller hard-fails
            logger.warning(
                f"[BEST_TRIAL] on-demand replay failed "
                f"({type(exc).__name__}: {exc}) — caller will hard-fail"
            )
            return None

    @staticmethod
    def _resolved_strategy_params(
        params_path: str,
        optuna_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Load resolved_params.json paired with the trial file, or None.

        None (always logged) → caller falls back to the legacy mapping:
        artifact absent, schema unknown, provenance sha256 mismatching the
        flat params just loaded (a STALE trial/resolved pair — e.g. the trial
        file was regenerated by an exporter that doesn't emit the companion),
        or any read error. Never raises.
        """
        try:
            from echolon._internal.strategy_files import (
                load_resolved_params,
                trial_params_fingerprint,
            )

            resolved = load_resolved_params(Path(params_path).parent)
            if resolved is None:
                return None
            expected = resolved.provenance.get("trial_params_sha256")
            if not expected:
                # The sha is load-bearing: an artifact without it cannot prove
                # it pairs with THIS trial file — never trust it.
                logger.warning(
                    "[BEST_TRIAL] resolved_params.json missing provenance sha "
                    "— falling back to legacy mapping"
                )
                return None
            if expected != trial_params_fingerprint(optuna_params):
                logger.warning(
                    "[BEST_TRIAL] resolved_params.json provenance mismatch "
                    "(stale trial/resolved pair) — falling back to legacy mapping"
                )
                return None
            logger.info(
                "[BEST_TRIAL] params source: resolved_params.json "
                f"(trial {resolved.provenance.get('trial_number')})"
            )
            return {key: dict(value) for key, value in resolved.components.items()}
        except Exception as exc:
            logger.warning(
                f"[BEST_TRIAL] resolved_params load failed — legacy mapping: {exc}"
            )
            return None


# =============================================================================
# BT-002 helper: raise EchelonError when a backtest completes with zero trades
# =============================================================================

from echolon.errors import raise_error


def _assert_trades_produced(
    total_trades: int,
    bars_processed: int,
    entry_signals_generated: int = 0,
    entry_signals_blocked: int = 0,
    risk_blocks: int = 0,
) -> None:
    """Raise BT-002 when a backtest completes with no trades. Logs the
    diagnostic warning first so the LLM reading logs sees both."""
    if total_trades > 0:
        return
    log_zero_trades_warning(
        get_run_context(),
        "Backtest",
        bars_processed=bars_processed,
        entry_signals_generated=entry_signals_generated,
        entry_signals_blocked=entry_signals_blocked,
        risk_blocks=risk_blocks,
    )
    raise_error(
        "BT-002",
        bars_processed=bars_processed,
        entry_signals_generated=entry_signals_generated,
        entry_signals_blocked=entry_signals_blocked,
        risk_blocks=risk_blocks,
    )
