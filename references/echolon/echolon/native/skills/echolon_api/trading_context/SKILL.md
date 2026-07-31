---
name: trading_context
description: Immutable dataclass carrying market, instrument, frequency, bar_size, and TradingTarget — exposes properties (market_code, instrument_code, bars_per_day), bar_size-aware phase encode/decode callbacks, and frequency-scaled indicator defaults.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.config.markets.core.context.TradingContext

## Purpose

`TradingContext` is the single value object threaded through every echolon module that touches market/instrument/frequency config. It bundles the `MarketConfig` (SHFE, CRYPTO, ...), the `InstrumentSpec` (al, btc, ...), a `frequency` string (`"intraday"` | `"interday"`), a `bar_size` string (`"5m"`, `"1h"`, `"1d"`, ...), an optional `TradingTarget` (user request, initial capital), and two callbacks `_encode_phase` / `_decode_phase` that `MarketFactory` wires up correctly for the given bar size. Downstream code reads properties (e.g. `ctx.market_code`, `ctx.bars_per_day`, `ctx.initial_capital`, `ctx.tradeable_phases`) and calls `ctx.encode_phase("morning")` rather than pulling raw config.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.config.markets.core.context import TradingContext

# 1. The canonical path: use MarketFactory to build a correctly-wired ctx.
ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 2. Thin convenience constructor (delegates to MarketFactory.create).
ctx = TradingContext.from_market(
    market="SHFE",
    instrument="al",
    frequency="intraday",
    bar_size="15m",
)

# 3. Read properties (see "Parameters / Returns" for the full list).
ctx.market_code              # "SHFE"
ctx.instrument_code          # "al"
ctx.is_intraday              # True
ctx.bars_per_day             # 23 (SHFE 15m with night session)
ctx.initial_capital          # 200_000.0 (or ctx.target.initial_capital)
ctx.tradeable_phases         # ['night', 'morning', 'afternoon']

# 4. Phase encoding for Backtrader data feeds (bar_size-aware).
ctx.encode_phase("morning")  # -> int
ctx.decode_phase(2)          # -> "morning" (5m/15m) or "day_session" (30m/1h)

# 5. Frequency-appropriate indicator defaults.
params = ctx.get_indicator_params()     # scaled to ctx.bar_size_minutes
rsi_len = ctx.hours_to_bars(2.3)        # bars for ~2.3h window
macd_fast = ctx.minutes_to_bars(25)
```

## When to use

- As the primary argument to every echolon backtest/deploy/data entry point. `EngineFactory.create_*`, `run_backtest`, `OptunaOptimizer`, `WFARunner`, `run_data_pipeline`, `run_indicator_calculation`, `load_backtest_data`, `load_indicator_metadata`, `get_strategy_class` — every one takes `ctx`. (Paradigm-specific machinery, e.g. TRS regime optimization, lives in the host application that registers a regime classifier; echolon ships none by default.)
- To compute frequency-appropriate indicator lookbacks in platform-agnostic strategy code: call `ctx.get_indicator_params()` or the `hours_to_bars` / `minutes_to_bars` helpers rather than hardcoding periods.
- To encode/decode SHFE session phases for a Backtrader data feed: always go through `ctx.encode_phase` / `ctx.decode_phase` — the factory picks the right granular (`night/morning/afternoon`) vs aggregated (`night_session/day_session`) lookup table based on `ctx.bar_size` at ctx construction time.
- Do *not* instantiate `TradingContext(...)` by hand outside of `MarketFactory`. The `_encode_phase`/`_decode_phase` callables default to trivial lambdas (`x → 0` / `x → 'unknown'`) and must be overridden per market × bar-size. `TradingContext.from_market` is the only sanctioned bypass.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| Dataclass fields | `market`, `instrument`, `frequency`, `bar_size`, optional `target` | — | The five user-visible inputs. `_encode_phase`/`_decode_phase` are private, factory-set. |
| Market properties | — | — | `market_code` (str), `timezone` (str), `has_contract_expiry` (bool). Read-through to `self.market`. |
| Instrument properties | — | — | `instrument_code`, `instrument_name`, `multiplier`, `margin_rate`, `has_night_session`, `initial_capital` (from `target` or 200_000 default). |
| `phases` / `trading_phases` | — | `Dict[str, SessionPhaseSpec]` / `list[SessionPhaseSpec]` | All phases (incl. breaks) / only trading phases. |
| `is_intraday` / `is_interday` | — | `bool` | Based on `self.frequency`. |
| `bars_per_day` | — | `int` | Looks up SHFE `BARS_PER_DAY` / `BARS_PER_DAY_NO_NIGHT` or CRYPTO `BARS_PER_DAY`; returns 1 for interday, 288 as a crypto fallback. |
| `bar_size_minutes` | — | `int` | Parses `"1m"`/`"5min"`/`"1h"`/`"1d"` (`1440`). |
| `bars_per_hour` | — | `int ≥ 1` | `max(1, 60 // bar_size_minutes)`. Interday (`1d`) / sub-hour-multiple bars floor to `1`. |
| `hours_to_bars(hours)` | `float` | `int ≥ 1` | `max(1, int(hours * bars_per_hour))`. |
| `minutes_to_bars(minutes)` | `int` | `int ≥ 1` | `max(1, minutes // bar_size_minutes)`. |
| `get_indicator_params()` | — | `dict` | Frequency-aware indicator defaults. Interday returns classic TA-Lib defaults (`rsi_period=14`, `adx_period=14`, `macd=12/26/9`, `channel_periods=[5,10,20]`, ...). Intraday scales those to `hours_to_bars(...)` so a 2.3h RSI period is constant across 5m/15m/1h bars. |
| `encode_phase(phase_str)` / `decode_phase(phase_code)` | `str` / `int` | `int` / `str` | Bar-size-aware: granular (`5m`/`15m`) uses `night=1, morning=2, afternoon=5`; aggregated (`30m`/`1h`) uses `night_session=1, day_session=2`. Returns `0` / `'unknown'` for unrecognised inputs. |
| `from_market(market, instrument, frequency='interday', bar_size='1d')` | strings | `TradingContext` | Classmethod — convenience wrapper calling `MarketFactory.create(...)`. |
| `is_aggregated_phases` / `tradeable_phases` | — | `bool` / `list[str]` | SHFE intraday: delegates to `echolon.config.markets.shfe.phases.is_aggregated_bar_size` / `get_tradeable_phases`. |

## Common errors

- **`bars_per_day` returning `None`** — `BARS_PER_DAY.get(self.bar_size)` on SHFE with an unmapped bar size (e.g. `"7m"`). No Echolon code — the caller typically trips a downstream TypeError. Restrict `bar_size` to the values in `EngineFactory.BAR_SIZE_MAP`.
- **`encode_phase` / `decode_phase` returning `0` / `'unknown'`** — `MarketFactory` failed to wire the callbacks for this bar size, or the caller passed a phase name that doesn't exist in the phase table (e.g. `"morning"` on 1h bars, where only `"day_session"` exists). Inspect `ctx.phases.keys()`.
- **`self.initial_capital == 200000.0` unexpectedly** — the ctx was constructed without a `TradingTarget`. Pass `initial_capital=` explicitly to `MarketFactory.create(...)`, or have your host application pre-load a `TradingTarget` from your session config and inject it via the factory.

## See also

- `market_factory` skill — builds `TradingContext` and sets the `_encode_phase`/`_decode_phase` callbacks.
- `engine_factory` skill — primary consumer; every `create_*` method takes a `ctx`.
- `load_backtest_data`, `load_indicator_metadata`, `run_data_pipeline`, `run_indicator_calculation` skills — all accept `ctx` as the first positional argument.
- echolon docs: `the config_reference skill`, `the component_guide skill`.
