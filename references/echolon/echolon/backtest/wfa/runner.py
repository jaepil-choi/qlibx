"""
Walk-Forward Analysis Runner
=============================

Orchestrates walk-forward analysis across multiple expanding windows.

For each window:
1. Filter indicators to IS period
2. Run Optuna optimization (N trials)
3. Select best robust trial via TrialSelector
4. Run OOS backtest with selected trial params
5. Collect IS/OOS metrics

After all windows:
6. Compute WFA aggregate metrics
7. Run final full-period backtest with last window's parameters
8. Augment backtest_results.json with WFA fields
"""

import gc
import json
import logging
import shutil
from pathlib import Path
from typing import Callable, Dict, Any, Mapping, Optional

import pandas as pd

from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig
from echolon.config.backtest_config import BacktestConfig
from echolon.errors import raise_error
from .window import WFAWindow, WFAConfig
from .analyzer import WalkForwardAnalyzer
from .drs_calculator import compute_drs, DRSConfig

logger = logging.getLogger(__name__)


def _apply_binding_overlay(
    params: Dict[str, Any], bindings: Mapping[str, Any],
) -> Dict[str, Any]:
    """Generic recursive key-overlay (Task #11 Stage 2, c2 — per-window
    rebinding pass-through).

    For every key present in ``bindings``, replace that key's value WHEREVER
    it occurs in ``params`` (at any nesting depth). Echolon carries no
    knowledge of what the keys mean (slot ids, indicator names, column
    names) or how ``params`` is nested (``entry_params`` / ``exit_params`` /
    ...) — that schema is entirely host-app-authored
    (``strategy_params.py``, dynamically loaded). This is safe precisely
    because host-app slot-keyed param names are unique across the whole
    param space by construction (qorka's T10 naming contract) — a recursive
    override can never collide with an unrelated key of the same name.

    Pure: returns a NEW nested dict; ``params`` is never mutated (the caller
    may reuse the original for the next window). ``bindings`` empty/None is
    a no-op fast path returning ``params`` unchanged (identity, not a copy)
    so the byte-identical-when-unused guarantee holds all the way through.
    """
    if not bindings:
        return params

    def _walk(node):
        if isinstance(node, dict):
            return {
                k: (bindings[k] if k in bindings else _walk(v))
                for k, v in node.items()
            }
        return node

    return _walk(params)


def _resolve_window_param_overlay(
    window: "WFAWindow",
    *,
    binding_resolver_fn: Optional[Callable[["WFAWindow"], Mapping[str, Any]]],
    base_search_space_fn: Callable,
    base_default_params: Dict[str, Any],
):
    """The ENTIRE (c2) per-window rebinding seam, extracted as a pure
    function so it is unit-testable without driving the full ``run()``
    Optuna/backtrader collaborator chain (mirrors the existing
    ``per_trial_returns`` source-pin precedent for anything that big — see
    ``test_wfa_runner_selection_passthrough.py`` — except this seam IS small
    enough to test directly, so it gets real assertions instead of a pin).

    ``binding_resolver_fn=None`` (default) -> returns the inputs UNCHANGED
    (identity) — byte-identical to pre-Task-#11 behavior. A resolver that
    returns an empty/falsy mapping for this window is likewise a no-op.
    Otherwise, both the per-trial search-space function AND the FIXED
    default-params dict used to reconstruct the winning trial's full vector
    (``TrialSelector.default_params``) are overlaid with the SAME bindings —
    so window k's IS-optimization (Step 2) AND the OOS backtest it hands off
    to (Step 4, via ``TrialSelector``-written ``selected_robust_trial.json``)
    see the identical per-window bindings; no separate Step-4 wiring needed.

    Echolon holds no rebinding policy: ``binding_resolver_fn`` is an opaque
    caller-supplied callable (mirrors ``selection_score_fn`` exactly) that
    the host app builds from ITS OWN slot/vintage/rebinder machinery.
    """
    if binding_resolver_fn is None:
        return base_search_space_fn, base_default_params
    bindings = binding_resolver_fn(window)
    if not bindings:
        return base_search_space_fn, base_default_params

    def _window_search_space_fn(trial, _fn=base_search_space_fn, _b=bindings):
        return _apply_binding_overlay(_fn(trial), _b)

    return _window_search_space_fn, _apply_binding_overlay(base_default_params, bindings)


def _assert_wfa_complete(all_windows, wfa_dir):
    """Hard-signal an INCOMPLETE WFA (B3, RCA 2026-06-21).

    A window whose ``TrialSelector`` finds no robust trial is skipped (Step 3
    ``continue``) and never overwrites ``selected_robust_trial.json``. If the
    runner then proceeded, Step 7's final full-period backtest would silently
    reuse the LAST-COMPLETED window's stale params over the whole history, and
    the DRS gates would score on the shrunken set of completed windows — a
    plausible-but-wrong verdict (No-Misleading-Fallback Policy). Refuse instead:

    - 0 windows completed   -> WFA-001 (unchanged behaviour)
    - some but not all      -> WFA-002 (the previously-silent middle case)
    - all windows completed -> return the completed-window list

    A window is "completed" iff it produced ``oos_results`` (a robust trial was
    selected and its OOS backtest ran).
    """
    completed = [w for w in all_windows if w.oos_results is not None]
    n_completed = len(completed)
    n_total = len(all_windows)

    if n_completed == 0:
        # Every window's trial_failure_summary.json already carries the
        # structured root cause; WFA-001 stops the pipeline and points at them.
        logger.error("WFA: No windows completed successfully — raising WFA-001")
        raise_error(
            "WFA-001",
            n_windows=n_total,
            reason="All WFA windows produced zero valid trials",
            suggestion=f"See per-window trial_failure_summary.json under {wfa_dir}",
        )

    if n_completed < n_total:
        failed_windows = [w.window_id for w in all_windows if w.oos_results is None]
        logger.error(
            f"WFA: incomplete — only {n_completed}/{n_total} windows produced a "
            f"robust trial (no survivors in windows {failed_windows}); refusing to "
            f"score a DRS from stale last-completed-window params — raising WFA-002"
        )
        raise_error(
            "WFA-002",
            n_completed=n_completed,
            n_total=n_total,
            failed_windows=failed_windows,
            suggestion=f"See per-window trial_failure_summary.json under {wfa_dir}",
        )

    return completed


class WFARunner:
    """
    Orchestrates walk-forward analysis across multiple windows.

    Each window gets independent Optuna optimization + TrialSelector + OOS backtest.
    After all windows, a final full-period backtest runs with the last window's
    parameters, and WFA robustness metrics are added to the results.
    """

    def __init__(
        self,
        ctx: TradingContext,
        config: WFAConfig,
        optuna_config: Optional[OptunaConfig] = None,
        backtest_config: Optional[BacktestConfig] = None,
        backtest_results_dir: Optional[Path] = None,
        wfa_dir: Optional[Path] = None,
        paths: Optional["PathsConfig"] = None,  # type: ignore[name-defined]
        drs_config: Optional[DRSConfig] = None,
        selection_score_fn: Optional[Callable[[pd.Series, Mapping[str, Any]], float]] = None,
        binding_resolver_fn: Optional[Callable[["WFAWindow"], Mapping[str, Any]]] = None,
        market_adapter_factory: Optional[Callable[..., Any]] = None,
    ):
        if optuna_config is None:
            raise ValueError(
                "optuna_config is required. Build one with OptunaConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._optuna_config = optuna_config

        if backtest_config is None:
            raise ValueError(
                "backtest_config is required. Build one with BacktestConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._backtest_config = backtest_config

        self.ctx = ctx
        self.config = config
        from echolon.config.paths_config import PathsConfig
        self._paths = paths if paths is not None else PathsConfig.from_env()
        if backtest_results_dir is None:
            backtest_results_dir = self._paths.backtest_results_dir
        self.output_dir = Path(backtest_results_dir)
        # wfa_dir holds the per-window archives. By default it nests under output_dir
        # (``{backtest_results_dir}/wfa_windows``) — back-compat for host apps that keep
        # the full backtest + WFA together. A host that separates run-types (e.g. qorka's
        # backtest/{full,wfa,replay}/ layout) passes an explicit sibling dir so the WFA
        # archives don't nest under the full-backtest dir.
        self.wfa_dir = Path(wfa_dir) if wfa_dir is not None else self.output_dir / "wfa_windows"

        # Caller provides DRSConfig explicitly (or None to run WFA without DRS
        # scoring). Host apps build this from their own target schema — echolon
        # no longer reaches into ctx.target workflow state.
        self._drs_config = drs_config

        # Generic pass-through to every per-window TrialSelector (mirrors
        # TrialSelector's own FLAG-1 hook). Default None reproduces the
        # built-in risk_adjusted_return.idxmax() ranking byte-for-byte — this
        # constructor carries the mechanism only, never a selection policy.
        self.selection_score_fn = selection_score_fn

        # Task #11 Stage 2 (c2) — generic per-window binding-resolver
        # pass-through, mirroring selection_score_fn exactly: an opaque
        # Callable[[WFAWindow], Mapping[str, Any]] invoked once per window,
        # BEFORE that window's IS-optimization (see run(), Step 2). Default
        # None reproduces prior behavior byte-for-byte — this constructor
        # carries NO rebinding policy (hysteresis/sign-guard/churn/ranking
        # all live in the host app; echolon only forwards the callable and
        # applies its returned mapping via the generic, schema-agnostic
        # _apply_binding_overlay).
        self.binding_resolver_fn = binding_resolver_fn

        # Generic host-app adapter construction hook. Default None preserves
        # Echolon's EngineFactory path; callers that need extra setup can return
        # any object satisfying the normal market-adapter interface.
        self.market_adapter_factory = market_adapter_factory

    def run(self) -> Dict[str, Any]:
        """
        Run complete WFA pipeline.

        Returns:
            Dict with final backtest_results.json content including WFA fields.
        """
        # Deferred imports (after cache clearing in orchestrator)
        from echolon.backtest.optimization.optuna_study import OptunaOptimizer
        from echolon.backtest.optimization.select_best_trial import TrialSelector
        from echolon.backtest.runner import run_best_trial
        from echolon.backtest.engine.backtest_runner import unlink_optional_series_artifacts
        from echolon.engine.factory import EngineFactory
        from echolon.backtest.engine.backtrader_strategy import get_strategy_class
        from echolon.data.loaders.backtest_data_loader import (
            load_backtest_data, load_indicator_metadata
        )
        # Load strategy_params dynamically from the configured strategy code
        # directory (paths.strategy_code_dir / "strategy_params.py" — exact
        # path is host-app-configurable via PathsConfig). StrategyLoader
        # handles the file-path → module resolution; a static import would
        # hardcode a pre-v0.3 path that no longer exists.
        from echolon.strategy.loader import StrategyLoader as _StrategyLoader
        _sp_loader = _StrategyLoader(self._paths.strategy_code_dir)
        _sp = _sp_loader.load_module("strategy_params")
        optuna_search_space = _sp.optuna_search_space
        DEFAULT_PARAMS = _sp.DEFAULT_PARAMS
        apply_shared_params = _sp.apply_shared_params
        framework = _sp.framework

        # Clean stale backtest artefacts from the prior run before starting
        # a fresh WFA pass. Cleanup target is
        # ``self._paths.backtest_results_dir`` (already injected).
        _stale_artefacts = [
            "backtest_results.json",
            "backtest_trades.csv",
            "equity_curve.csv",
            "optimization_trials.csv",
            "full_trial_selection_record.json",
            "optuna_study_info.json",
        ]
        for _name in _stale_artefacts:
            _p = Path(self.output_dir) / _name
            if _p.exists():
                _p.unlink()
                logger.info(f"[WFA] cleaned stale artefact: {_name}")

        # Load full indicators ONCE (covers entire date range). Inject the
        # configured paths so the loader resolves market_data_dir +
        # indicators_backtest_dir without falling back to from_env().
        full_indicators, trading_calendar_df = load_backtest_data(
            ctx=self.ctx,
            indicator_dir=self._paths.indicators_backtest_dir,
            market_data_dir=self._paths.market_data_dir,
        )
        indicator_metadata = load_indicator_metadata(
            ctx=self.ctx,
            indicator_dir=self._paths.indicators_backtest_dir,
        )
        if not isinstance(full_indicators.index, pd.DatetimeIndex):
            full_indicators.index = pd.to_datetime(full_indicators.index)
        full_indicators = full_indicators.sort_index()

        # Create market adapter and strategy class ONCE. Thread the paths
        # roots into the adapter (so SHFE adapter resolves main_contract.csv
        # without raising CFG-003) and the bridge strategy params (so
        # _register_indicators finds its indicators dir and
        # _initialize_strategy doesn't fall back to from_env()).
        if self.market_adapter_factory is not None:
            market_adapter = self.market_adapter_factory(
                ctx=self.ctx,
                paths=self._paths,
            )
        else:
            market_adapter = EngineFactory.create_market_adapter(
                ctx=self.ctx,
                mode="backtest",
                market_data_dir=self._paths.market_data_dir,
            )
        strategy_class = get_strategy_class(
            ctx=self.ctx,
            strategy_code_dir=str(self._paths.strategy_code_dir),
            indicators_backtest_dir=str(self._paths.indicators_backtest_dir),
        )

        # Create per-window storage
        self.wfa_dir.mkdir(parents=True, exist_ok=True)

        for window in self.config.windows:
            logger.info(
                f"\n{'='*80}\n"
                f"WFA WINDOW {window.window_id}: "
                f"IS={window.is_start} -> {window.is_end}, "
                f"OOS={window.oos_start} -> {window.oos_end}\n"
                f"{'='*80}"
            )
            print(
                f"\n{'='*80}\n"
                f"WFA WINDOW {window.window_id}/{len(self.config.windows)}: "
                f"IS={window.is_start} -> {window.is_end}, "
                f"OOS={window.oos_start} -> {window.oos_end}\n"
                f"{'='*80}"
            )

            window_dir = self.wfa_dir / f"window_{window.window_id}"
            window_dir.mkdir(parents=True, exist_ok=True)

            # Task #11 Stage 2 (c2): resolve this window's binding overlay
            # BEFORE Step 2's IS-optimization (join key is window.window_id,
            # not a re-derived is_end/fit_end arithmetic — the host app's
            # resolver is responsible for that lookup). No-op end to end
            # when binding_resolver_fn is None (the constructor default).
            window_search_space_fn, window_default_params = _resolve_window_param_overlay(
                window,
                binding_resolver_fn=self.binding_resolver_fn,
                base_search_space_fn=optuna_search_space,
                base_default_params=DEFAULT_PARAMS,
            )

            # --- Step 1: Filter IS data ---
            is_start_ts = pd.Timestamp(window.is_start)
            is_end_ts = pd.Timestamp(window.is_end)
            is_indicators = full_indicators[
                (full_indicators.index >= is_start_ts) &
                (full_indicators.index <= is_end_ts)
            ].copy()

            if is_indicators.empty:
                logger.warning(f"Window {window.window_id}: No IS data, skipping")
                continue

            logger.info(
                f"Window {window.window_id}: IS data "
                f"{is_indicators.index[0].date()} -> {is_indicators.index[-1].date()}, "
                f"{len(is_indicators)} bars"
            )

            # --- Step 2: Run Optuna optimization on IS ---
            optimizer = OptunaOptimizer(
                ctx=self.ctx,
                market_adapter=market_adapter,
                strategy_class=strategy_class,
                search_space_fn=window_search_space_fn,
                n_trials=self.config.trials_per_window,
                optimization_target=self.config.optimization_target,
                run_context="optimization",
                optuna_config=self._optuna_config,
                paths=self._paths,
            )

            study, _best_params = optimizer.run(
                indicators=is_indicators,
                trading_calendar_df=trading_calendar_df,
                study_name=f"WFA_window_{window.window_id}",
                indicator_metadata=indicator_metadata,
                # Persist per-window trial_failure_summary.json alongside
                # optimization_trials.csv. LLM debugger agents consume this
                # as the canonical AI-readable breadcrumb.
                failure_report_dir=window_dir,
                failure_report_window_id=window.window_id,
            )

            # Save per-window optimization results
            if study:
                optimizer.save_study_results(
                    study=study,
                    output_dir=str(window_dir),
                    save_trials_csv=True,
                    save_best_params=True,
                )

            # Extract IS sharpe from study
            window.is_sharpe = self._extract_is_sharpe(study)

            # --- Step 3: Select robust trial ---
            trials_csv_path = window_dir / "optimization_trials.csv"
            if not trials_csv_path.exists():
                logger.warning(f"Window {window.window_id}: No trials CSV, skipping")
                continue

            selector = self._build_selector(
                trials_csv_path=trials_csv_path,
                window_dir=window_dir,
                default_params=window_default_params,
                apply_shared_params_fn=apply_shared_params,
                param_classifications=framework.get_param_classifications(),
                search_space_fn=window_search_space_fn,
                # `optimizer` (Step 2, same scope) is the live OptunaOptimizer
                # instance for THIS window — its _per_trial_returns dict is
                # already in memory (populated during optimizer.run()), so
                # there's no need to reload the per_trial_returns.json
                # save_study_results just wrote to window_dir. Forwarded
                # unconditionally: TrialSelector only reads it when
                # selection_score_fn is set, so this is a no-op on the
                # default (None) path.
                per_trial_returns=optimizer._per_trial_returns,
            )
            selected_trial = selector.select()
            window.selected_trial = selected_trial

            if not selected_trial:
                logger.warning(f"Window {window.window_id}: No robust trial found, skipping OOS")
                continue

            logger.info(
                f"Window {window.window_id}: Selected trial "
                f"#{selected_trial.get('trial_number', '?')} from "
                f"cluster {selected_trial.get('cluster_id', '?')}"
            )

            # --- Step 4: Run OOS backtest ---
            # TrialSelector saved THIS window's selection (+ resolved_params
            # .json companion) into self._paths.strategy_code_dir — the exact
            # dir run_best_trial reads below (paths.best_params_file). The
            # explicit strategy_code_dir kwarg above is load-bearing: the
            # env-based default resolves to a DIFFERENT dir under run
            # isolation (the stale-read defect).
            unlink_optional_series_artifacts(self.output_dir)
            oos_results = run_best_trial(
                ctx=self.ctx,
                start_date=window.oos_start,
                end_date=window.oos_end,
                backtest_config=self._backtest_config,
                paths=self._paths,
            )

            window.oos_results = oos_results
            window.oos_sharpe = oos_results.get('sharpe_ratio_annual', 0.0)

            # --- Step 5: Archive per-window OOS artifacts ---
            self._archive_window_artifacts(window, window_dir)

            wfe_str = (
                f"{window.walk_forward_efficiency:.3f}"
                if window.walk_forward_efficiency is not None else "N/A"
            )
            logger.info(
                f"Window {window.window_id}: "
                f"IS_sharpe={window.is_sharpe:.3f}, "
                f"OOS_sharpe={window.oos_sharpe:.3f}, "
                f"WFE={wfe_str}"
            )
            print(
                f"Window {window.window_id} complete: "
                f"IS_sharpe={window.is_sharpe:.3f}, "
                f"OOS_sharpe={window.oos_sharpe:.3f}, "
                f"WFE={wfe_str}"
            )

            # Memory cleanup between windows
            del is_indicators, study
            gc.collect()

        # --- Step 6: Compute WFA metrics from per-window OOS results ---
        # B3 (RCA 2026-06-21): an INCOMPLETE WFA (some windows produced no robust
        # trial) must hard-fail, not silently proceed — Step 7's final backtest would
        # otherwise reuse the last-completed window's STALE params over the full period
        # and score the DRS gates on a shrunken window set (No-Misleading-Fallback).
        completed_windows = _assert_wfa_complete(self.config.windows, self.wfa_dir)

        wfa_analyzer = WalkForwardAnalyzer(completed_windows)
        wfa_summary = wfa_analyzer.compute_summary()
        wfa_window_details = wfa_analyzer.compute_window_details()

        # --- Step 7: Final full-period backtest with last window's params ---
        # Last window's TrialSelector saved selected_robust_trial.json (+
        # resolved_params.json) into self._paths.strategy_code_dir — the dir
        # run_best_trial() reads (paths.best_params_file) — and backtests
        # across the full BACKTEST_START_DATE → BACKTEST_END_DATE.
        # This produces consistent performance_metrics, trades, and equity curve
        # all from one parameter set — no artificial stitching.
        logger.info(
            "Running final full-period backtest with last window's parameters..."
        )
        print(
            "\n" + "="*80 + "\n"
            "FINAL FULL-PERIOD BACKTEST (with last window's robust parameters)\n"
            + "="*80
        )
        run_best_trial(ctx=self.ctx, backtest_config=self._backtest_config, paths=self._paths)

        # --- Step 8: Augment backtest_results.json with WFA fields ---
        last_window = completed_windows[-1]
        final_results = self._build_final_results(
            last_window=last_window,
            wfa_summary=wfa_summary,
            wfa_window_details=wfa_window_details,
        )

        drs_score = final_results.get('drs', {}).get('drs_score', 0) or 0
        logger.info(
            f"\nWFA COMPLETE: {len(completed_windows)}/{len(self.config.windows)} windows, "
            f"OOS Sharpe mean={(wfa_summary.get('oos_sharpe_mean') or 0):.3f}, "
            f"WFE mean={(wfa_summary.get('wfe_mean') or 0):.3f}, "
            f"DRS={drs_score:.1f}/100"
        )

        return final_results

    def _build_selector(
        self,
        *,
        trials_csv_path: Path,
        window_dir: Path,
        default_params: Dict[str, Any],
        apply_shared_params_fn,
        param_classifications,
        search_space_fn,
        per_trial_returns: Optional[Mapping] = None,
    ) -> "TrialSelector":  # noqa: F821 — imported lazily below, like run() does
        """Construct the per-window TrialSelector.

        STALE-READ GUARD (load-bearing, regression-tested): the selection MUST
        be written to ``self._paths.strategy_code_dir`` — the exact dir
        ``run_best_trial`` reads (``paths.best_params_file``). TrialSelector's
        own default falls back to ``PathsConfig.from_env()``, which is a
        DIFFERENT dir under host-app run isolation; with that default, every
        OOS window silently executes whatever stale selected_robust_trial.json
        sits at the read path (proven incident: one identical executed vector
        across all 5 windows while the selector picked 5 different trials).

        ``search_space_fn`` enables the resolved_params.json companion export
        (the optimizer-exact nested vector; consumers prefer it over the lossy
        flat-name mapping).

        ``selection_score_fn`` (from the WFARunner constructor) and
        ``per_trial_returns`` (the calling window's in-memory
        ``OptunaOptimizer._per_trial_returns``, or ``None`` when unavailable)
        are forwarded verbatim to TrialSelector's own FLAG-1 hook — this
        method carries no selection policy of its own.
        """
        from echolon.backtest.optimization.select_best_trial import TrialSelector

        return TrialSelector(
            trial_data_path=str(trials_csv_path),
            output_dir=str(window_dir),
            max_drawdown_threshold=self.config.max_drawdown_threshold,
            default_params=default_params,
            apply_shared_params_fn=apply_shared_params_fn,
            param_classifications=param_classifications,
            strategy_code_dir=self._paths.strategy_code_dir,
            search_space_fn=search_space_fn,
            selection_score_fn=self.selection_score_fn,
            per_trial_returns=per_trial_returns,
        )

    def _extract_is_sharpe(self, study) -> float:
        """Extract the best IS sharpe from the Optuna study."""
        if study is None:
            return 0.0

        completed = [t for t in study.trials if t.state.name == 'COMPLETE']
        if not completed:
            return 0.0

        # For multi-objective, values[0] is sharpe_ratio
        best_sharpe = max(t.values[0] for t in completed)
        return float(best_sharpe)

    def _archive_window_artifacts(self, window: WFAWindow, window_dir: Path):
        """
        Copy OOS backtest artifacts from ``self.output_dir`` (typically
        ``paths.backtest_results_dir``) to the per-window directory for
        record-keeping.
        """
        src_dir = self.output_dir
        for filename in ["backtest_results.json", "backtest_trades.csv", "equity_curve.csv"]:
            src = src_dir / filename
            if src.exists():
                dst = window_dir / f"oos_{filename}"
                shutil.copy2(str(src), str(dst))

    def _build_final_results(
        self,
        last_window: WFAWindow,
        wfa_summary: Dict[str, Any],
        wfa_window_details: list,
    ) -> Dict[str, Any]:
        """
        Augment the full-period backtest_results.json with WFA fields.

        At this point, run_best_trial() has already written consistent
        backtest_results.json, backtest_trades.csv, and equity_curve.csv
        from the full-period backtest. We just add WFA robustness data.
        """
        results_path = self.output_dir / "backtest_results.json"
        if results_path.exists():
            with open(results_path, 'r') as f:
                final_data = json.load(f)
        else:
            logger.error("No backtest_results.json from full-period backtest")
            final_data = {}

        # Add WFA fields (additive — does not touch performance_metrics)
        final_data["wfa_summary"] = wfa_summary
        final_data["wfa_windows"] = wfa_window_details

        # Compute Deployment Readiness Score from WFA + performance data.
        # Host app must inject drs_config via the constructor — echolon no
        # longer derives it from ctx.target workflow state.
        drs_result = compute_drs(final_data, config=self._drs_config)
        final_data["drs"] = drs_result.to_dict()

        # Copy last window's optimization_trials.csv to main backtest dir
        last_window_dir = self.wfa_dir / f"window_{last_window.window_id}"
        src_trials = last_window_dir / "optimization_trials.csv"
        if src_trials.exists():
            shutil.copy2(str(src_trials), str(self.output_dir / "optimization_trials.csv"))

        # Re-save augmented backtest_results.json
        with open(results_path, 'w') as f:
            json.dump(final_data, f, indent=4, default=str)

        logger.info(
            f"Final backtest_results.json augmented with "
            f"{len(wfa_window_details)} WFA window details"
        )
        return final_data
