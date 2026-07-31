---
name: config_reference
description: Pydantic config models exposed by echolon — BacktestConfig, OptunaConfig, IndicatorConfig, TradingContext, PathsConfig — and the env vars that resolve them. Use when constructing configs at program entry, threading PathsConfig through the public entry points, or migrating from removed module-level constants.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: phase_f9b_docs_migration
---

# Configuration Reference

Echolon uses Pydantic v2 models for all configuration. Each model is a typed object — IDEs and LLMs can introspect it via `model_json_schema()` or via `echolon schema <type>`.

## BacktestConfig

`echolon.config.backtest_config.BacktestConfig` — single-run backtest settings. Common mistakes: `CFG-001` (`end_date < start_date`), `CFG-002` (missing directory). See the `engine_factory` skill for end-to-end use.

## OptunaConfig

`echolon.config.optuna_config.OptunaConfig` — hyperparameter search settings. The `target` field accepts:

- `"sharpe_ratio"` — maximize risk-adjusted return (default)
- `"total_return"` — maximize absolute return
- `"annual_return"` — maximize annualized return
- `"drawdown"` — minimize max drawdown
- `"multi_objective"` — Pareto frontier over Sharpe + drawdown

See the `optuna_optimizer` skill for invocation details.

## IndicatorConfig

`echolon.config.indicator_config.IndicatorConfig` — period caps that the auto-clamp logic in `generate_strategy_params` consults. Most users never override the defaults.

## TradingContext

`echolon.config.markets.core.context.TradingContext` — runtime context: market, instrument, frequency, bar size. Don't construct directly; use `MarketFactory.create(market, instrument, frequency, bar_size)`. See the `market_factory` and `trading_context` skills.

## quick_start convenience

For common cases, use the top-level convenience helper:

```python
from echolon import quick_start

ctx, bt, opt = quick_start(
    market="shfe",
    instrument="cu",
    start_date="2020-01-01",
    end_date="2023-12-31",
)
# Override anything
opt.n_trials = 500
bt.max_drawdown_pct = 20.0
```

`quick_start` uses env vars for paths with fallbacks to `./workspace` and `./data`.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ECHOLON_WORKSPACE_DIR` | `./workspace` | Workspace root |
| `ECHOLON_DATA_DIR` | `./data` | Market data + indicators |
| `ECHOLON_LOG_LEVEL` | `INFO` | Logging verbosity |
| `ECHOLON_N_JOBS_DEFAULT` | `-1` | Default Optuna parallelism |
| `ECHOLON_PROJECT_ROOT` | `<cwd>` | Resolved by `PathsConfig.from_env()` |
| `ECHOLON_SESSION_DIR` | `<root>/session` | Session-state directory (consumed by host applications that load session JSON; not by `MarketFactory` itself) |

Set via shell export, `.env` file, or Docker env config.

## PathsConfig

`echolon.config.paths_config.PathsConfig` is the single Pydantic model that owns every directory and file path the library touches. Unlike other configs, **`PathsConfig` is REQUIRED at entry points** — host applications construct it once and inject it through the public entry points (`run_data_pipeline`, `run_live_data_update`, `run_backtest`, `run_indicator_calculation`, etc.).

If you don't supply one, the library falls back to a conventional layout rooted at `ECHOLON_PROJECT_ROOT` (defaults to cwd). That's fine for scripts but anti-pattern for PyPI library consumption.

### Construction

**From a conventional project root** (recommended for host applications with their own project layout):

```python
from pathlib import Path
from echolon.config.paths_config import PathsConfig

paths = PathsConfig.from_project_root(Path("/path/to/my_project"))
```

This produces the layout:
- `<root>/session/`
- `<root>/workspace/{data,current}/...`
- `<root>/output/`
- `<root>/data/`

**From platformdirs** (recommended for pip-installed end-users without a project layout):

```python
paths = PathsConfig.from_platformdirs("echolon")
# Linux: ~/.local/share/echolon/...
# macOS: ~/Library/Application Support/echolon/...
# Windows: %APPDATA%/echolon/...
```

`platformdirs` ships as a hard dep with echolon; no extras needed.

**Explicit overrides** (any field):

```python
paths = PathsConfig.from_project_root(
    root,
    market_data_dir=Path("/mnt/bigdisk/md"),
)
```

### Injection at entry points

```python
from echolon.config.markets.factory import MarketFactory
from echolon.data import run_data_pipeline, run_live_data_update

ctx = MarketFactory.create(market="SHFE", instrument="al", frequency="interday", bar_size="1d")
run_data_pipeline(ctx, paths=paths)
run_live_data_update(ctx, client, paths=paths)
```

### Fields

| Field | Default (conventional layout) | Description |
|---|---|---|
| `project_root` | `<root>` | Required root |
| `session_dir` | `<root>/session` | User inputs (state.json, targets) |
| `workspace_dir` | `<root>/workspace` | Runtime working directory |
| `output_dir` | `<root>/output` | Final outputs (reports, archives) |
| `raw_data_dir` | `<root>/data` | Raw source data from API/exchange |
| `market_data_dir` | `<workspace>/data/market_data` | Processed OHLCV + calendar |
| `indicators_research_dir` | `<workspace>/data/indicators/research` | Full research indicators |
| `indicators_backtest_dir` | `<workspace>/data/indicators/backtest` | Strategy-selected indicators |
| `current_dir` | `<workspace>/current` | Current iteration workspace |
| `strategy_code_dir` | `<current>/code` | Generated strategy files |
| `backtest_results_dir` | `<current>/backtest` | Backtest outputs |
| `current_analysis_dir` | `<current>/analysis` | Market metrics outputs |
| `best_params_file` | `<strategy_code>/selected_robust_trial.json` | Optimized params |
| `deploy_config_file` | `<session>/deploy_config.json` | Live deploy config |

### Migration from module-level constants

Earlier versions exposed module-level constants like `MARKET_DATA_DIR`, `INDICATORS_BACKTEST_DIR`, `PLATFORM_AGNOSTIC_DIR` at `echolon.config.settings`. These are all deleted. Migrate by:

```python
# OLD (no longer works)
from echolon.config.settings import MARKET_DATA_DIR
run_data_pipeline(ctx)
# used MARKET_DATA_DIR implicitly

# NEW
from echolon.config.paths_config import PathsConfig
paths = PathsConfig.from_project_root(project_root)
run_data_pipeline(ctx, paths=paths)
# explicitly uses paths.market_data_dir
```

`echolon.config.settings` has been removed entirely. Use `PathsConfig.from_env()` (honors `ECHOLON_PROJECT_ROOT`, falls back to cwd) when you need a lazily-resolved root, or `PathsConfig.from_project_root(<root>)` for an explicit root.

## See also

- CLI: `echolon schema BacktestConfig` (or `OptunaConfig`, `IndicatorConfig`) dumps the full Pydantic JSON schema
- Skill: `market_factory` — TradingContext construction
- Skill: `engine_factory` — passing configs into the backtest engine
- Skill: `optuna_optimizer` — invocation
