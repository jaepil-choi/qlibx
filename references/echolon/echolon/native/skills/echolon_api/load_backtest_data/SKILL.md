---
name: load_backtest_data
description: Loads pre-calculated strategy indicators and the market trading calendar for a TradingContext; coerces contract and session_phase columns into numeric form for Backtrader, surfaces IND-003 NaN-ratio warnings, and returns a (indicators_df, calendar_df) tuple.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.data.loaders.backtest_data_loader.load_backtest_data

## Purpose

`load_backtest_data(ctx, ...)` is the single entry point for reading the two CSVs every backtest needs: `strategy_indicators.csv` (OHLCV + pre-calculated indicators per bar) and `trading_calendar.csv` (trading dates + session metadata). It resolves paths from `PathsConfig.from_env()` by default — `indicators_backtest_dir/{instrument}/strategy_indicators.csv` and `market_data_dir/{MARKET}/{instrument}/trading_calendar.csv` — parses datetimes, converts SHFE contract strings like `'al1803'` to numeric `1803` (Backtrader lines must be numeric), encodes `session_phase*` columns via `ctx.encode_phase` (bar-size-aware), and surfaces any `IND-003` NaN sidecar warnings written by the indicator processor.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.data.loaders.backtest_data_loader import load_backtest_data
from echolon.config.paths_config import PathsConfig

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Default: reads from PathsConfig.from_env() locations.
indicators_df, calendar_df = load_backtest_data(ctx)

# 2. Explicit path to a specific indicators CSV (e.g. per-slot).
indicators_df, _ = load_backtest_data(
    ctx,
    indicators_path="/home/user/output/slot_3/strategy_indicators.csv",
)

# 3. Inject PathsConfig dirs (preferred over env when orchestrating
#    multiple instances in one process).
paths = PathsConfig.from_env()
indicators_df, calendar_df = load_backtest_data(
    ctx,
    indicator_dir=paths.indicators_backtest_dir,
    market_data_dir=paths.market_data_dir,
)

# 4. Typical downstream consumers:
#    - OptunaOptimizer.run(indicators=indicators_df, trading_calendar_df=calendar_df, ...)
#    - BacktestRunner.load_data() -> uses this internally.
```

## When to use

- At the top of any backtest / optimization workflow. `BacktestRunner.load_data()`, `WFARunner.run()`, and custom Optuna scripts all call `load_backtest_data(ctx=...)` before constructing the engine.
- When you need the indicators DataFrame indexed by `datetime` (intraday) or `date` (interday), with `session_phase*` columns pre-encoded to ints and `contract` column pre-converted to integer contract identifiers — exactly what Backtrader's data feed expects.
- Do *not* call `pd.read_csv` on `strategy_indicators.csv` yourself. You will miss the datetime index, the contract-to-numeric conversion, the bar-size-aware phase encoding, and the IND-003 sidecar warnings.
- Do *not* rely on the deprecated `ECHOLON_PROJECT_ROOT`-based fallback paths — always pass `indicator_dir` / `market_data_dir` explicitly when you have a `PathsConfig` available.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `load_backtest_data(ctx, indicators_path=None, *, indicator_dir=None, market_data_dir=None)` | `TradingContext`; optional full CSV path; optional dirs (keyword-only) | `tuple[pd.DataFrame, pd.DataFrame]` | `(indicators_data, trading_calendar)`. Indicators indexed by `datetime` (if column present) else `date`; always sorted chronologically with `index.name = None` to avoid backtrader conflicts. |
| Path resolution | — | — | `indicators_path` default: `{indicator_dir or PathsConfig.from_env().indicators_backtest_dir}/{ctx.instrument_name}/strategy_indicators.csv`. Calendar path: `{market_data_dir or PathsConfig.from_env().market_data_dir}/{MARKET_UPPER}/{ctx.instrument_name}/trading_calendar.csv`. |
| Numeric coercion | — | — | `contract` column: `_convert_contract_to_numeric('al1803', 'al') → 1803`. Any `session_phase*` column: `ctx.encode_phase(value)` (int), `NaN → 0`. |
| Sidecar warnings | — | — | If `<indicators_path>.warnings.json` exists, logs each `IND-003` warning row: `indicator '<col>' has <nan_ratio>% NaN (<nan_rows>/<rows> rows)`. Corrupt sidecars are swallowed silently (best-effort). |
| Related helpers in same module | `load_best_params(path)` | `dict` | Reads any JSON-encoded params file. `load_indicator_metadata(ctx, ...)` — see the `load_indicator_metadata` skill. |

## Common errors

- **`FileNotFoundError: [Errno 2] ... strategy_indicators.csv`** — the indicator calculation step never ran, or `indicator_dir` points somewhere empty. Run `run_indicator_calculation(ctx, output_dir=...)` first, or correct the path. No Echolon code.
- **`FileNotFoundError` on `trading_calendar.csv`** — the data pipeline never produced a calendar. Run `run_data_pipeline(ctx, ...)` first (it writes the calendar in Step 1.5 via `CalendarGenerator`). No Echolon code.
- **`IND-003` warnings** (logger-level only, not raised) — an indicator column has high NaN ratio. Does not halt the backtest, but typically indicates a buggy indicator definition or a contract-gap issue. See `echolon/native/errors/codes/IND-003.md`.
- **`TypeError: unorderable types` from Backtrader** — the `contract` or `session_phase*` column was not numeric. Should never happen through this loader, but will surface if a custom `indicators_path` points to a CSV that did not come from the echolon pipeline.
- **`KeyError: 'datetime'` or `'date'`** — the CSV has no datetime or date column. The loader checks `'datetime' in indicators_data.columns` first, then `'date'`; if neither exists it proceeds without setting an index. Downstream Backtrader will likely crash. Regenerate indicators.

## See also

- `load_indicator_metadata` skill — pairs with this loader for indicator column metadata.
- `run_data_pipeline` skill — produces `trading_calendar.csv`.
- `run_indicator_calculation` skill — produces `strategy_indicators.csv` + `strategy_indicator_metadata.json`.
- `trading_context` skill — supplies `ctx.market_code`, `ctx.instrument_name`, `ctx.instrument_code`, and the bar-size-aware `ctx.encode_phase` used here.
- `optuna_optimizer`, `wfa_runner`, `run_best_trial` skills — consumers of the returned `(indicators_df, calendar_df)` tuple.
