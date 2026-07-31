---
name: market_factory
description: Factory entry point that builds a fully-wired TradingContext from explicit market/instrument/frequency/bar_size parameters. Single canonical constructor (`create`) plus introspection helpers for instrument lookup and registry walking.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.config.markets.factory.MarketFactory

## Purpose

`MarketFactory` is the single entry point for obtaining a configured `TradingContext`. Given explicit `market`, `instrument`, `frequency`, and `bar_size`, it (1) resolves the market config from the registered set (currently SHFE; CRYPTO is scaffolded but not production), (2) looks up the instrument spec by code, (3) attaches market-specific phase encode/decode functions for the bar size, and (4) returns a ready-to-use `TradingContext`. Every downstream module — backtest, strategy, evaluation — should obtain its context via this factory rather than constructing `TradingContext` directly.

## Interface

```python
from echolon.config.markets.factory import MarketFactory

# Canonical constructor: explicit market/instrument/frequency/bar_size.
ctx = MarketFactory.create(
    market="SHFE",
    instrument="cu",
    frequency="interday",
    bar_size="1d",
)

# Optional initial_capital override (defaults to 200_000.0).
ctx = MarketFactory.create(
    market="SHFE",
    instrument="al",
    frequency="intraday",
    bar_size="5m",
    initial_capital=500_000.0,
)

# Flexible instrument lookup (by code OR human name).
spec = MarketFactory.get_instrument_flexible("SHFE", "aluminum")  # or "al"

# Introspection helpers.
cfg       = MarketFactory.get_market_config("SHFE")
all_codes = MarketFactory.list_instruments("SHFE")
```

## When to use

- At every module entry point that needs market/instrument/frequency info — call `MarketFactory.create(...)` once and pass the returned `TradingContext` down via dependency injection. Don't re-construct.
- When you need to validate that a market/instrument combination is supported before doing heavier work — `get_instrument_flexible` returns `None` instead of raising.
- Do *not* instantiate `TradingContext` by hand. The factory is responsible for wiring the phase encode/decode callbacks correctly for each market and bar size.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `create(market, instrument, frequency, bar_size, initial_capital=200000.0)` | market code (`"SHFE"`/`"CRYPTO"`), instrument code, `"intraday"` or `"interday"`, bar size string, optional float | `TradingContext` | Explicit construction. Raises `ValueError` for unsupported market or instrument. |
| `get_market_config(market)` | market code | `MarketConfig \| None` | Raw market config with timezone, sessions, instrument registry. |
| `get_instrument(market, instrument)` | market code, instrument code | `InstrumentSpec \| None` | Strict lookup by code. |
| `get_instrument_flexible(market, identifier)` | market code, code OR human name | `InstrumentSpec \| None` | Lookup by either `"al"` or `"aluminum"`. Case-insensitive. |
| `list_instruments(market)` | market code | `list[str]` | All supported instrument codes for the market. |
| `clear_cache()` | — | `None` | Clears the internal `_market_configs` cache. For tests only. |

Note: there is no `from_session()`, `load_target()`, or `build()` method. Prior versions of this skill referenced those — they never existed in the public API. If you need session-state loading (mapping a session config file to a `TradingTarget` + `TradingContext`), that's a host-application concern; build it on top of `MarketFactory.create(...)` in your own factory layer.

## Common errors

- **`ValueError: Unsupported market: '...'`** — `create` / `get_instrument_flexible` was called with a market code outside `{'SHFE', 'CRYPTO'}`. Add a loader branch in `MarketFactory._load_market` to register the new market.
- **`ValueError: Unsupported instrument: '...' for market '...'`** — the instrument code/name is not in that market's `instruments` registry. Check `MarketFactory.list_instruments(market)` or the market's `config.py`.

## See also

- `trading_context` skill — the `TradingContext` object `MarketFactory` returns
- echolon docs: the `config_reference` skill, the `component_guide` skill
