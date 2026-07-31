---
name: run_data_pipeline
description: End-to-end file-based market-data pipeline — extracts raw OHLCV, generates the trading calendar, standardizes + session-filters + resamples + splits by contract; writes outputs under PathsConfig.market_data_dir/{market}/{instrument}/.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.data.run_data_pipeline

## Purpose

`run_data_pipeline(ctx, ...)` orchestrates the full file-based market-data pipeline for a single `(market, instrument, frequency, bar_size)` tuple. It runs five steps — raw extraction → calendar generation → standardization → session-filter (intraday) → resample (intraday) → contract split — plus a SHFE-only Step 2.5 that builds session-availability metadata and enhances the calendar with per-date session flags. Outputs land under `PathsConfig.market_data_dir/{market}/{instrument}/`. For live/incremental updates use `echolon.data.live_data.run_live_data_update` instead.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.config.paths_config import PathsConfig
from echolon.data import run_data_pipeline     # or run_pipeline (alias)

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Full pipeline from raw data. Writes to
#    paths.market_data_dir / ctx.market_code / ctx.instrument_name / ...
ok = run_data_pipeline(ctx)

# 2. Reuse existing raw data (skip Step 1). Typical during iteration.
ok = run_data_pipeline(ctx, skip_extraction=True)

# 3. Explicit PathsConfig injection + date range.
paths = PathsConfig.from_env()
ok = run_data_pipeline(
    ctx,
    paths=paths,
    start_date="2018-01-01",
    end_date="2024-12-31",
)

# 4. Minute-bar extraction from SHFE API with an explicit start contract.
ok = run_data_pipeline(
    ctx,                                 # ctx.is_intraday == True
    start_contract="2301",
    start_date="2023-01-01",
    end_date="2024-12-31",
)
```

## When to use

- As the one-shot way to (re)generate the CSVs under `paths.market_data_dir` for a given market/instrument/bar-size. The downstream indicator pipeline, backtester, and live updater all read from there.
- When you need the `trading_calendar.csv` to exist *before* standardization (the pipeline intentionally runs `CalendarGenerator` at Step 1.5 so `OHLCVStandardizer` can derive `trading_date` for night-session bars).
- When working with SHFE intraday data — Step 2.5 (`SHFESessionAnalyzer`) writes session-availability info that downstream consumers depend on for holiday handling. Only SHFE + intraday triggers this step.
- Do *not* use this for live incremental updates. `run_live_data_update` (in the same module family) handles MiniQMT-style per-bar ingestion. The file pipeline assumes batch full-history input.
- Do *not* add `from __future__ import annotations` to this module — the code comment at the top explicitly disallows it because the paths-injection smoke test reads the `paths` parameter annotation at runtime via `inspect.signature()`.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `run_data_pipeline(ctx, *, paths=None, input_dir=None, output_dir=None, start_date=None, end_date=None, skip_extraction=False, start_contract=None)` | `TradingContext`; optional `PathsConfig`; optional dir overrides; ISO date strings; `skip_extraction` bool; minute-only `start_contract` | `bool` | `True` on success; `False` if extraction or loading produced empty data. |

Step sequence (see `backtest_data.py`):
1. **Extract raw** (skipped if `skip_extraction=True`) via `_get_extractor(market, instrument, frequency, paths)`. Returns `SHFEFileDayExtractor` for day data, `SHFEApiMinuteExtractor` for minute data. CRYPTO extractor is `NotImplementedError`. For minute API: also calls `extractor.download_minute_data(start_contract, period='1m', output_dir=...)` when `start_contract` is provided.
1.5. **Generate calendar** via `CalendarGenerator(output_dir, timezone).generate(df, start_date, end_date)` — only if `trading_calendar.csv` doesn't already exist.
2. **Standardize** via `OHLCVStandardizer(fill_missing=True, market, trading_calendar, bar_size).standardize(raw_data, timezone=ctx.timezone)`.
2.5. **SHFE session analysis** (intraday SHFE only) — `SHFESessionAnalyzer(bar_size_minutes, bar_size).analyze_from_ohlcv(...)`. Saves `session_availability.*`, enhances `trading_calendar.csv`.
3. **Filter sessions** (intraday only) — `SessionFilter(market).filter(df)` removes out-of-session bars.
4. **Resample** (intraday, when `bar_size != "1m"`) — `OHLCVResampler(target_frequency=bar_size).resample(df)`.
5. **Split by contract** — `ContractSplitter(output_dir).split(df)`.

Output layout (on success): `{paths.market_data_dir}/{market}/{instrument}/`
- `trading_calendar.csv` (enhanced with SHFE session availability when applicable)
- `sort_by_date.csv` — raw standardized (via ContractSplitter or pre-extracted)
- `sort_by_contract/{contract}.csv` — per-contract OHLCV after ContractSplitter
- `session_availability.*` (SHFE intraday only)

## Common errors

- **`NotImplementedError: Crypto extractor not yet implemented`** — CRYPTO market support for this pipeline is TODO. `_get_extractor` raises when `market_upper == "CRYPTO"`.
- **`ValueError: Unsupported frequency: 'hourly'`** — `_get_extractor` accepts only `"day"` and `"minute"` / `"1m"` / `"5m"` / `"15m"` / `"1h"`. Anything else raises.
- **`ValueError: Unsupported market: 'X'`** — neither SHFE nor CRYPTO.
- **`ValueError: Cannot parse bar_size '...'`** — `_parse_bar_size_minutes` accepts only formats ending in `min`, `m`, `h`, `d`.
- **Silent `False` return with `[DATA_PIPELINE] Extraction failed: no data` or `... No existing data found to process`** — extractor returned empty. For `skip_extraction=True` on day data: check `{paths.raw_data_dir}/{market}/{instrument_code}/sort_by_date.csv` exists; for minute: check `{paths.raw_data_dir}/{market}/{instrument_code}/minute_data/*.csv`.
- **`KeyError` from `MarketFactory.get_instrument_flexible`** — `_load_source_data` fails if the instrument code/name is unknown. Fix `ctx.instrument_code` / `ctx.instrument_name`.

## See also

- `load_backtest_data` skill — downstream reader that consumes `trading_calendar.csv` and `strategy_indicators.csv`.
- `run_indicator_calculation` skill — runs after this pipeline to produce `strategy_indicators.csv`.
- `trading_context` skill — supplies `ctx.market_code`, `ctx.instrument_name`, `ctx.is_intraday`, `ctx.bar_size`, `ctx.timezone`.
- `market_factory` skill — `MarketFactory.get_instrument_flexible` used in `_load_source_data`.
- echolon docs: `echolon/data/__init__.py` (public API surface), `echolon/data/live_data.py` (`run_live_data_update`).
