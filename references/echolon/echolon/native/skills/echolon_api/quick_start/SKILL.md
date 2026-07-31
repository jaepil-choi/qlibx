---
name: quick_start
description: Five-step onboarding from pip install to first running backtest. Use when an agent is starting from zero and needs the canonical happy-path sequence (init → validate → customize → run).
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: phase_f9b_docs_migration
---

# Quick Start

Install echolon, scaffold a strategy, validate, customize, run a backtest. Five commands; the entire happy-path.

## 1. Install

```bash
pip install echolon
```

## 2. Scaffold a strategy

```bash
echolon init my_first --template minimal
```

This copies one of the bundled scaffolds from `echolon/native/templates/` into `./my_first/`. Available templates: `minimal`, `momentum_breakout`, `rsi_mean_reversion`. Every template ships 8 files:

- `strategy.py` — coordinator (`strategy_main` class)
- `entry.py` / `exit.py` / `risk.py` / `sizer.py` — components
- `strategy_params.py` — parameter declarations + Optuna search space
- `strategy_indicator_list.json` — declared indicators
- `README.md` — template notes

The `minimal` template is a HOLD-forever scaffold — runs end-to-end with zero trades. Use it to confirm wiring before adding logic.

## 3. Validate

```bash
echolon validate my_first/
```

Runs all preflight checks and reports any structured `EchelonError` with `[CODE]` prefixes. Pass means the strategy is loadable and conformant.

## 4. Customize

Edit `entry.py`, `exit.py`, `sizer.py`. Use `self.get_indicator(f"name_{self.period}")` for indicator access; declared columns come from `strategy_indicator_list.json`. See the `trading-api-core` skill for the component contract.

## 5. Run a backtest

```bash
# Inside a workspace produced by `echolon init` (instrument/start/end recovered from .echolon-workspace.json):
echolon backtest single my_first/

# If no marker is present, pass the ctx explicitly:
echolon backtest single my_first/ --instrument cu --start 2020-01-01 --end 2023-12-31
```

`backtest single` re-validates first; pass `--unsafe` to skip (not recommended; the validators are the agent's safety net). Add `--json` for machine-readable metrics.

## On error

Every `EchelonError` carries `[CODE]`, `what`, `why`, `fix`, `context`, `docs_url`. Workflow:

1. Read the formatted exception text.
2. The `Fix:` line is parameterized with concrete context (file, line, missing field, etc.).
3. For deeper context (worked example, related codes), call MCP `get_error_doc(code)` or read `echolon/native/errors/codes/{code}.md` from the installed package.

## PathsConfig (for non-trivial deploys)

A pip-installed library shouldn't bind to your cwd. Construct a `PathsConfig` at your program's entry point and inject it:

```python
from pathlib import Path
from echolon.config.paths_config import PathsConfig
from echolon.config.markets.factory import MarketFactory
from echolon.data import run_data_pipeline

paths = PathsConfig.from_project_root(Path("/data/echolon-proj"))
ctx = MarketFactory.create(market="SHFE", instrument="al", frequency="interday", bar_size="1d")
run_data_pipeline(ctx, paths=paths, skip_extraction=False)
```

For pip-installed end-users without a project layout, use `PathsConfig.from_platformdirs("echolon")` (platformdirs ships as a hard dep with echolon). See the `config_reference` skill for full `PathsConfig` field listing.

## Common errors at this stage

- **STR-001** (missing required file) — your scaffold drift; copy from a fresh `echolon init`.
- **PRM-002** (params shape) — `DEFAULT_PARAMS` is missing one of `entry_params` / `exit_params` / `risk_params` / `sizer_params`.
- **CFG-001** (`end_date < start_date`) — flip the dates.
- **DAT-001** (OHLCV file missing) — the data pipeline didn't write to `paths.market_data_dir/{market}/{instrument}/`. Run `run_data_pipeline` first.

## See also

- Skill: `trading-api-core` — full component contract
- Skill: `config_reference` — PathsConfig / BacktestConfig / OptunaConfig
- Skill: `parameter-patterns` — strategy_params.py architecture
- CLI: `echolon --help` (every subcommand has `--help`)
- MCP tools: `validate_strategy`, `scaffold_component`, `get_error_doc`, `list_indicators`
