---
name: run_best_trial
description: Runs a single Backtrader backtest using parameters from selected_robust_trial.json (TrialSelector output), optionally overriding the start/end dates for out-of-sample validation; returns the detailed results dict.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.backtest.runner.run_best_trial

## Purpose

`run_best_trial(ctx, best_params_path=None, start_date=None, end_date=None, backtest_config=None, *, paths)` is the thin functional wrapper around `BacktestRunner.best_trial(...)` that runs a backtest with the parameters picked by `TrialSelector` (written to `selected_robust_trial.json`). When `best_params_path` is `None`, the runner reads from `paths.best_params_file` (which defaults to `{paths.strategy_code_dir}/selected_robust_trial.json`). `paths: PathsConfig` is a required kwarg — pass the same `PathsConfig` you used everywhere else in the pipeline; there is no implicit env fallback. This is the standard way to replay the winning Optuna trial on either the full period or an out-of-sample window, and it logs a one-line `[BEST_TRIAL] Backtest::SUCCESS` summary with Sharpe, return, drawdown, trades, and win rate.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.config.paths_config import PathsConfig
from echolon.backtest.runner import run_best_trial

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")
paths = PathsConfig.from_project_root("/path/to/your/workspace")

# 1. Default: reads selected_robust_trial.json from paths.best_params_file,
#    runs over the default backtest period (BacktestConfig.start/end).
results = run_best_trial(ctx, paths=paths)

# 2. OOS slice (used by WFARunner for per-window OOS backtests).
oos = run_best_trial(
    ctx,
    start_date="2023-01-01",
    end_date="2023-06-30",
    paths=paths,
)

# 3. Custom params file (e.g. a cached or hand-edited trial).
results = run_best_trial(ctx, best_params_path="/tmp/my_trial.json", paths=paths)

# 4. Other entry points in the same module — all require paths= too.
from echolon.backtest.runner import run_debug_backtest, run_backtest
debug_results  = run_debug_backtest(ctx, paths=paths)                            # uses DEFAULT_PARAMS
custom_results = run_backtest(ctx, strategy_params={...}, run_context="custom", paths=paths)
```

## When to use

- After an Optuna study + `TrialSelector.select()` has written `selected_robust_trial.json` into the strategy code directory, and you want to validate that trial over the full period or an OOS window.
- Inside `WFARunner.run()` — called once per window for the OOS slice and once more for the final full-period backtest with the last window's parameters. The function does not accept a parameters dict argument; it always reads from disk via `BacktestRunner.best_trial`.
- From the CLI `python -m echolon.backtest.runner --mode best_trial --market <M> --instrument <I> --frequency <F> --bar-size <B>`. `main()` calls `MarketFactory.create(...)` with those kwargs, then routes to `run_best_trial`.
- Do *not* use this to run a freshly-optimized set of parameters that hasn't been written to `selected_robust_trial.json` yet — use `run_backtest(ctx, strategy_params=…)` instead.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `run_best_trial(ctx, best_params_path=None, start_date=None, end_date=None, backtest_config=None)` | `TradingContext`; optional path to params JSON; optional ISO date strings `YYYY-MM-DD`; optional `BacktestConfig` | `Dict[str, Any]` | Delegates to `BacktestRunner.best_trial(ctx=…, params_path=…, start_date=…, end_date=…, backtest_config=…)`. |
| `run_debug_backtest(ctx, backtest_config=None)` | ctx, optional config | `Dict[str, Any]` | Quick iteration — uses strategy module's `DEFAULT_PARAMS`, verbose logging. Delegates to `BacktestRunner.debug(...)`. |
| `run_backtest(ctx, strategy_params=None, run_context='backtest', enable_strategy_logging=True, output_dir=None, save_results=True, backtest_config=None)` | explicit params dict or None (falls back to `DEFAULT_PARAMS`) | `Dict[str, Any]` | Most flexible entry. Builds `_RunnerConfig`, calls `runner.load_data()` then `runner.run(...)`. |

Returned dict includes at least (all values may be 0 if the backtest trades nothing): `sharpe_ratio_annual`, `total_return_pct`, `max_drawdown_pct`, `total_trades`, `win_rate_pct`, plus trade log / equity curve references written to disk when `save_results=True`. Results files land under `PathsConfig.backtest_results_dir` (or `output_dir` override for `run_backtest`).

## Common errors

- **`FileNotFoundError` on `selected_robust_trial.json`** — `best_params_path` is `None` and `paths.best_params_file` (= `{paths.strategy_code_dir}/selected_robust_trial.json` by convention) does not exist. Run `TrialSelector.select()` first, or pass an explicit `best_params_path`. No Echolon code issued.
- **`pydantic.ValidationError` from `SelectedTrialSchema`** — the JSON on disk has the wrong shape (e.g. from hand-edits or a stale format). Re-run `TrialSelector.select()` to rewrite the file via `SelectedTrialSchema.model_validate(...).model_dump()`.
- **`BT-001`** — any exception inside the platform-agnostic strategy's `_execute_bar()` (or any callback it invokes — entry, exit, risk, sizer component methods) during the replay. `on_bar()` is the Template Method that calls `_execute_bar()`; strategies override `_execute_bar()` only. See `echolon/native/errors/codes/BT-001.md` and the `get_strategy_class` skill.
- **`CFG-001`** — if the caller-supplied `start_date`/`end_date` or underlying `BacktestConfig` has `end_date < start_date`. See `echolon/native/errors/codes/CFG-001.md`.

## See also

- `trial_selector` skill — writes the `selected_robust_trial.json` that this function reads.
- `wfa_runner` skill — calls `run_best_trial` for each OOS window + the final full-period replay.
- `engine_factory` skill — `BacktestRunner` internally calls `EngineFactory.create_backtest_engine(ctx, ...)`.
- `market_factory` skill — `MarketFactory.create(market, instrument, frequency, bar_size)` is the canonical way to obtain the `ctx` argument.
