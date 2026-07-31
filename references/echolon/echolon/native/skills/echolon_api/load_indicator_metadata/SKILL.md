---
name: load_indicator_metadata
description: Reads strategy_indicator_metadata.json for a TradingContext from the configured indicators directory; returns a dict used by the backtrader bridge to register indicator lines on the data feed.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.data.loaders.backtest_data_loader.load_indicator_metadata

## Purpose

`load_indicator_metadata(ctx, metadata_path=None, *, indicator_dir=None)` reads the `strategy_indicator_metadata.json` sidecar produced by the indicator pipeline. The returned dict carries (among other keys) `indicator_columns` — the list of indicator column names that `BacktraderStrategyBridge._register_indicators()` iterates over to wire each indicator into the engine's market-data interface. The function is a thin JSON reader; it does no schema validation beyond `json.load`.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.data.loaders.backtest_data_loader import load_indicator_metadata
from echolon.config.paths_config import PathsConfig

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Default: reads PathsConfig.from_env().indicators_backtest_dir /
#    {instrument} / strategy_indicator_metadata.json.
metadata = load_indicator_metadata(ctx)
metadata["indicator_columns"]  # -> ['rsi_14', 'ema_12', ...]

# 2. Explicit metadata path — BacktraderStrategyBridge uses this
#    to pick up per-slot metadata at
#    indicators_backtest_dir/<slot_name>/strategy_indicator_metadata.json.
metadata = load_indicator_metadata(
    ctx,
    metadata_path="/path/to/slot/strategy_indicator_metadata.json",
)

# 3. Inject indicator_dir (kept consistent with load_backtest_data).
paths = PathsConfig.from_env()
metadata = load_indicator_metadata(ctx, indicator_dir=paths.indicators_backtest_dir)
```

## When to use

- When building a custom optimization / backtest harness that needs to pass `indicator_metadata=...` into `OptunaOptimizer.run(...)` (which hands it to `OptimizationRunner.setup_shared_data(...)` so worker processes know which Backtrader lines to create).
- Inside `BacktraderStrategyBridge._register_indicators()`, which calls this to discover the indicator columns on the data feed. That call runs once per Backtrader strategy instance — you rarely need to call it yourself if you're using the standard runners.
- Do *not* hand-write the columns list in code. The metadata JSON is the authoritative contract between the indicator pipeline and the backtest engine; re-reading it keeps the two in sync when indicator definitions change.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `load_indicator_metadata(ctx, metadata_path=None, *, indicator_dir=None)` | `TradingContext`; optional full JSON path; optional dir (keyword-only) | `Dict[str, Any]` | `json.load(...)` of the metadata file. |
| Path resolution | — | — | `metadata_path` default: `{indicator_dir or PathsConfig.from_env().indicators_backtest_dir}/{ctx.instrument_name}/strategy_indicator_metadata.json`. |

Known keys (observed in consumers; not schema-validated here):
- `indicator_columns` — list of indicator column names on the data feed. Used by `BacktraderStrategyBridge._register_indicators`, which filters out `{'date', 'contract', 'unnamed: 14', 'trading_date'}` (lowercased) and lowercases the remaining names into backtrader line names.
- Additional keys may be present (e.g. calibration info, regime params) depending on how `run_indicator_calculation` was invoked; inspect the JSON to confirm.

## Common errors

- **`FileNotFoundError: [Errno 2] ... strategy_indicator_metadata.json`** — the indicator pipeline never wrote the sidecar, or the path is wrong. Run `run_indicator_calculation(ctx, output_dir=indicator_dir/instrument, ...)` first, or correct `indicator_dir`. No Echolon code.
- **`json.JSONDecodeError`** — the sidecar file is corrupt. Regenerate via `run_indicator_calculation`.
- **Silent failure when `indicator_columns` is missing** — `BacktraderStrategyBridge._register_indicators` wraps the lookup in `if 'indicator_columns' in metadata:` and will register *zero* indicators otherwise. Strategy code that reaches for an indicator will then raise at `on_bar` time and surface as `BT-001`. Ensure the metadata JSON has the key.

## See also

- `load_backtest_data` skill — paired loader for the indicators DataFrame itself.
- `run_indicator_calculation` skill — produces the metadata JSON.
- `get_strategy_class` skill — the `BacktraderStrategyBridge._register_indicators` method that consumes this metadata at strategy-init time.
- `trading_context` skill — supplies `ctx.instrument_name` for path resolution.
