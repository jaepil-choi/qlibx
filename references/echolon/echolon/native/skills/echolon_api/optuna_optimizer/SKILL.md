---
name: optuna_optimizer
description: Optuna TPE study driver with parallel ProcessPoolExecutor backtesting, recoverable-vs-critical error classification, and optional multi-objective optimization; runs N trials of a strategy against pre-loaded indicators and returns the Optuna study plus best params.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.backtest.optimization.optuna_study.OptunaOptimizer

## Purpose

`OptunaOptimizer` wraps Optuna's TPE sampler around echolon's `OptimizationRunner` so that a strategy's parameter search space (defined as a `search_space_fn(trial: optuna.Trial) -> dict`) is explored over N trials with either single- or multi-objective targets (`"sharpe_ratio"`, `"total_return"`, `"multi_objective"`). Trials run in parallel via `ProcessPoolExecutor`; contract prices and indicator DataFrames are pre-loaded once and shared across forked workers. The optimizer classifies errors into a RECOVERABLE whitelist (`ZeroDivisionError`, `ValueError`, `OverflowError`, `FloatingPointError`) vs. CRITICAL (everything else, including `KeyError`/`AttributeError`) — critical errors stop the study immediately so broken strategy code fails fast.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.config.optuna_config import OptunaConfig
from echolon.engine.factory import EngineFactory
from echolon.backtest.engine.backtrader_strategy import get_strategy_class
from echolon.backtest.optimization.optuna_study import OptunaOptimizer
from echolon.data.loaders.backtest_data_loader import (
    load_backtest_data, load_indicator_metadata,
)

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")
market_adapter = EngineFactory.create_market_adapter(ctx)
strategy_class = get_strategy_class(ctx)
indicators, calendar = load_backtest_data(ctx)
metadata = load_indicator_metadata(ctx)

from my_strategy.strategy_params import optuna_search_space

# 1. Required: pass an OptunaConfig (ValueError if omitted).
optimizer = OptunaOptimizer(
    ctx=ctx,
    market_adapter=market_adapter,
    strategy_class=strategy_class,
    search_space_fn=optuna_search_space,
    optuna_config=OptunaConfig(n_trials=100, target="sharpe_ratio"),
)

# 2. Run optimization. Returns (study, best_params) — or (study, None)
#    for multi-objective studies.
study, best_params = optimizer.run(
    indicators=indicators,
    trading_calendar_df=calendar,
    study_name="my_study",
    indicator_metadata=metadata,
)

# 3. Persist results (CSV + JSON) for TrialSelector / debugging.
optimizer.save_study_results(
    study,
    output_dir="/path/to/output",
    save_trials_csv=True,
    save_best_params=True,
)

# 4. Sequential mode for debugging (n_jobs=1, no subprocess).
optimizer = OptunaOptimizer(..., use_sequential=True, optuna_config=OptunaConfig(n_trials=10))
```

## When to use

- Inside any optimization pass — `WFARunner.run` is the canonical echolon caller (re-instantiates `OptunaOptimizer` once per WFA window, sharing the same `market_adapter` and `strategy_class` across windows). Host applications running their own iterative-refinement orchestrators wrap `OptunaOptimizer` directly.
- When you need process-parallel trial execution and want Optuna's TPE with `multivariate=True, seed=42, n_startup_trials=20, n_ei_candidates=48` (those values are hard-coded here — do not expect to override them via config).
- In debug workflows: pass `use_sequential=True` so every trial runs in-process with a TQDM progress bar and standard Python traceback on failure.
- Do *not* construct `OptimizationRunner.setup_shared_data(...)` yourself — `OptunaOptimizer.run()` handles shared-data setup and teardown around the study. The Note at line ~517 of `optuna_study.py` calls out that `self._run_trial_in_process` was removed specifically to avoid pickling `self` (which holds an unpicklable `ctx` with lambda phase-encode functions).

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `__init__(ctx, market_adapter, strategy_class, search_space_fn, n_trials=None, optimization_target=None, timeout=None, use_sequential=False, run_context="optimization", optuna_config=<required>, indicator_dir=None)` | see above | — | Builds the optimizer. `optuna_config` is required (raises `ValueError` if `None`). Explicit kwargs (`n_trials`, `optimization_target`, `timeout`) override `optuna_config` values for back-compat. `indicator_dir` defaults to `PathsConfig.from_env().indicators_backtest_dir`; used to preload contract prices. |
| `run(indicators, trading_calendar_df=None, regime_data=None, study_name=None, indicator_metadata=None, failure_report_dir=None, failure_report_window_id=None)` | pre-loaded indicators DataFrame + optional calendar, regime data, indicator metadata dict + optional failure-report target dir + window id (added in commit `54a9f29`) | `Tuple[Optional[optuna.Study], Optional[Dict[str, Any]]]` | Creates a TPE study (`direction='maximize'` single-obj or `directions=['maximize']*3` for `multi_objective`), preloads contracts, dispatches trials to `ProcessPoolExecutor` (or sequentially), tears down shared data afterward. When `failure_report_dir` is provided and any trial fails, also writes a structured `trial_failure_summary.json` next to the other artifacts and emits a boxed stderr block summarizing the top failure groups (aggregated via `echolon.backtest.optimization.failure_reporter`). |
| `save_study_results(study, output_dir, save_trials_csv=True, save_best_params=True)` | completed study, output dir | `None` | Writes `optimization_trials.csv` (`study.trials_dataframe()`) and `best_params.json` (trial number, best value, params, user attrs). |
| Helpers — classmethods | — | — | `is_recoverable_error(error)` — `isinstance(error, RECOVERABLE_ERRORS_WHITELIST)`. `check_for_critical_errors_callback(study, trial)` — stops the study and raises `RuntimeError` if `trial.user_attrs['CRITICAL_ERROR']` is set. `format_time_seconds(seconds)` — "1.2m" / "2.5h" strings. |
| Module helper | `_raise_constraint_violation(trial_number, constraint, required, actual, params)` | `None` (raises) | Raises `BT-003` with Optuna trial params for callers implementing hard constraints. |

User-attrs set on each trial: `sharpe_ratio`, `max_drawdown_pct`, `annual_return_pct`, `total_trades`. For multi-objective: `values = (sharpe, max_drawdown_pct, annual_return)` with all three `maximize` — `max_drawdown_pct` is expected negative, so "maximize" means "least negative".

## Common errors

- **`ValueError: optuna_config is required. Build one with OptunaConfig(...) ...`** — `__init__` called without `optuna_config`. Always pass one; `echolon.quick_start()` provides defaults.
- **`RuntimeError: CRITICAL STRATEGY ERROR in trial N: ...`** — a trial raised something *not* in `RECOVERABLE_ERRORS_WHITELIST`. The strategy code has a bug (typically `KeyError`/`AttributeError` from a bad indicator name). Fix the strategy and rerun — the study is stopped on purpose.
- **`RuntimeError: CRITICAL: <error_message>`** — same class of failure, raised from `_objective` when a trial's `OptimizationRunner` returns `success=False` with a non-recoverable error. The trial's user attrs carry `CRITICAL_ERROR`, `error_type`, `error_message`.
- **`BT-003`** — raised by `_raise_constraint_violation` when a hard constraint (e.g. minimum trades) fails. See `echolon/native/errors/codes/BT-003.md`.
- **Zero completed trials** — all trials failed with recoverable errors. The optimizer logs `log_workflow_failure("optimization", ..., f"All {failed_trials} trials failed - check strategy code")`, emits a boxed stderr block (via `failure_reporter.render_terminal()`) with the top-N failure groups + exemplar tracebacks + docs URLs, writes `trial_failure_summary.json` to `failure_report_dir` if provided (commit `54a9f29`), and returns `(study, None)`. **Primary diagnostic source:** `trial_failure_summary.json` (structured JSON — read `groups[0].error` for the dominant failure). Secondary: `optimization_trials.csv`.
- **`TypeError: cannot pickle 'function' object`** (historical) — do not reintroduce `self._run_trial_in_process`; the module-level `run_optimization_trial` is used precisely so `ctx`'s lambdas never cross process boundaries.

## See also

- `trial_selector` skill — consumes `optimization_trials.csv` written by `save_study_results`.
- `wfa_runner` skill — instantiates an `OptunaOptimizer` per WFA window.
- `engine_factory` skill — supplies `market_adapter` via `create_market_adapter(ctx)`.
- `get_strategy_class` skill — supplies `strategy_class` for the `strategy_class` argument.
- `load_backtest_data`, `load_indicator_metadata` skills — supply the `indicators`, `trading_calendar_df`, `indicator_metadata` arguments to `run()`.

## Failure aggregation (added in Part B1)

Per-trial exceptions in `OptimizationRunner.run_trial` no longer vanish into
worker-process log handlers (which don't propagate to the parent under
`ProcessPoolExecutor`). They return as a structured `OptimizationFailure`
dataclass (`echolon/backtest/engine/failure.py`) carrying the exception
type, catalog code (when raised via `raise_error`), tail-truncated
traceback, context dict, and trial params. `OptunaOptimizer._run_parallel`
aggregates them via `failure_reporter.aggregate()` into `FailureGroup`s
keyed by `(error_type, error_code, first_line(message))`, keeping one
exemplar traceback per group. At end-of-study, `render_terminal()` prints
a boxed stderr summary and `write_json_artifact()` persists the groups to
`trial_failure_summary.json` when `failure_report_dir` is set.

Commits that landed this flow: `b37702b` (OptimizationFailure dataclass),
`b6cfe4e` (structured worker→controller return), `37ae1ec` (failure_reporter
aggregate/render/persist), `54a9f29` (controller aggregation + kwargs on
`run()`), `c4de31b` (WFARunner threads `failure_report_dir` per window).
