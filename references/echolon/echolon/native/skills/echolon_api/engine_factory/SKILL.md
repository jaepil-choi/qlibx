---
name: engine_factory
description: Factory for trading engines — composes a market adapter, frequency context, and market-mode-appropriate hooks (ContractAwareHook / SessionAwareHook) into a ready-to-use backtest or deploy engine from a TradingContext.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.engine.factory.EngineFactory

> Note on import path: pre-v0.3 docs listed this as `echolon.backtest.engine_factory.EngineFactory` or `echolon.quant_engine.engine_factory.EngineFactory`. Both module paths are gone — `echolon/native/cli/migrate.py` rewrites the old paths to `echolon.engine.factory`, and every live caller (`wfa/runner.py`, `engine/backtest_runner.py`, `engine/optimization_runner.py`, `live/slot/trading_slot.py`) imports from `echolon.engine.factory`. Use `from echolon.engine.factory import EngineFactory`.

## Purpose

`EngineFactory` is the single place that knows how to assemble a configured trading engine. Given a `TradingContext`, it (1) constructs the right `IMarketAdapter` (SHFE, CRYPTO), (2) builds the matching `IFrequencyContext` (interday → `InterdayContext`; intraday → `IntradayContext` with bars-per-day derived from market sessions), and (3) adds hooks based on market × frequency: `ContractAwareHook` for interday futures (rollover + expiry), `SessionAwareHook` for any intraday trading. For live deployment it returns a `QMTEngine` (miniqmt) instead.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.engine.factory import EngineFactory

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Backtest engine (BacktraderEngine) with hooks pre-installed.
engine = EngineFactory.create_backtest_engine(
    ctx,
    indicators_dir="/path/to/indicators",         # required for ContractAwareHook
    strategy_logger_enabled=True,
    strategy_logger_dir="/path/to/logs",
)

# 2. Deploy engine (live trading). Only the "miniqmt" platform is
#    implemented today; any other platform name raises ValueError.
deploy_engine = EngineFactory.create_deploy_engine(ctx, client=my_qmt_client)

# 3. Building blocks alone (used internally by create_backtest_engine
#    and by WFARunner to share a market adapter across windows).
market_adapter    = EngineFactory.create_market_adapter(ctx)
frequency_context = EngineFactory.create_frequency_context(ctx, market_adapter)

# 4. Extension / introspection.
EngineFactory.register_market_adapter("CME", CMEAdapter)
EngineFactory.get_available_markets()       # ['SHFE', 'CRYPTO']
EngineFactory.get_available_bar_sizes()     # ['1m', '5m', '15m', ...]
```

## When to use

- At the top of any backtest orchestration — `BacktestRunner`, `OptimizationRunner`, `WFARunner` all call `EngineFactory.create_backtest_engine(ctx=…)` or `create_market_adapter(ctx=…)` to share a single market adapter across trials/windows.
- At the top of any live deployment — `echolon.live.slot.trading_slot.TradingSlot` calls `EngineFactory.create_deploy_engine(ctx, client=…, deferred_execution=True)` to obtain a `QMTEngine`.
- When adding a new market: call `EngineFactory.register_market_adapter("CME", CMEAdapter)` before any engine creation. The `MARKET_ADAPTERS` registry is class-level, so registration persists for the process.
- Do *not* construct `BacktraderEngine`, `SHFEAdapter`, `IntradayContext`, etc. by hand for a backtest run. Hook composition (interday-futures → `ContractAwareHook`; intraday → `SessionAwareHook`) is centralised here and must stay consistent.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `create_market_adapter(ctx, calendar_path=None)` | `TradingContext`; optional SHFE calendar CSV path | `IMarketAdapter` | Instantiates `SHFEAdapter(symbol, trading_calendar_path=…)` or `CryptoAdapter(symbol=…)` from `ctx.market_code` and `ctx.instrument_code`. |
| `create_frequency_context(ctx, market_adapter=None)` | `TradingContext`; optional adapter for bars-per-day | `IFrequencyContext` | `InterdayContext()` for `frequency=="interday"` / `bar_size in ("1d","daily")`; else `IntradayContext(bar_size=<BarSize enum>, bars_per_day=<derived>, flatten_before_close=True, flatten_bars_before_close=0)`. |
| `create_backtest_engine(ctx, calendar_path=None, indicators_dir=None, strategy_logger_enabled=True, strategy_logger_dir=None)` | as above | `BacktraderEngine` | Backtest engine. `ContractAwareHook` added when `ctx.has_contract_expiry and is_interday and indicators_dir` is set (needs `ContractIndicatorManager`). `SessionAwareHook` added for any intraday ctx. |
| `create_deploy_engine(ctx, calendar_path=None, client=None, platform=None)` | as above + a `MiniQMTClient`, platform name (`"miniqmt"` default and only supported value) | `ITradingEngine` (`QMTEngine`) | Live deploy engine. Raises `ValueError` for any platform other than `"miniqmt"`. |
| `register_market_adapter(market_code, adapter_class)` | `str`, `Type[IMarketAdapter]` | `None` | Extend the factory. Writes to `MARKET_ADAPTERS` (class-level dict). |
| `get_available_markets()` | — | `list[str]` | Keys of `MARKET_ADAPTERS`. |
| `get_available_bar_sizes()` | — | `list[str]` | Keys of `BAR_SIZE_MAP` (`1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`, `1w`, plus `*min` aliases). |

`BAR_SIZE_MAP` maps both `"5m"`/`"5min"` to `BarSize.MINUTE_5`, etc. `CME` is registered as a TODO in the registry comment.

## Common errors

- **`ValueError: Unknown market: 'X'. Available: SHFE, CRYPTO`** — `create_market_adapter` called with a market code that isn't in `MARKET_ADAPTERS`. Register via `EngineFactory.register_market_adapter` or add the loader.
- **`ValueError: Unknown or unimplemented platform: '<name>'`** — `create_deploy_engine(platform="<anything-but-miniqmt>")`. Only `"miniqmt"` is implemented today; there is no `live/platforms/ccxt/` (or any other broker) module. Drop the `platform=` kwarg or pass `"miniqmt"`.
- **Silent hook omission on interday futures backtests** — if `indicators_dir` is `None`, `ContractAwareHook` is not added even when `ctx.has_contract_expiry and is_interday`. Symptoms: no contract rollover, wrong PnL. Always pass `indicators_dir` for futures backtests. No Echolon error code.
- **Downstream `BT-001`** — any hook or the underlying `BacktraderEngine` may raise `BT-001` during `next()`. See `echolon/native/errors/codes/BT-001.md` and the `get_strategy_class` skill.

## See also

- `market_factory` skill — produces the `TradingContext` consumed here.
- `trading_context` skill — the object threaded through every `create_*` call.
- `get_strategy_class` skill — the Backtrader strategy class eventually run by `BacktraderEngine`.
- echolon docs: `the component_guide skill`, `the patterns skill`.
