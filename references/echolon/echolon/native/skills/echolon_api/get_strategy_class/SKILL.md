---
name: get_strategy_class
description: Returns a cached Backtrader-compatible strategy class (BacktraderStrategyBridge subclass) bound to a TradingContext; optional strategy_code_dir loads platform-agnostic strategy files from an arbitrary directory.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.backtest.engine.backtrader_strategy.get_strategy_class

## Purpose

`get_strategy_class(ctx, strategy_code_dir=None, indicators_backtest_dir=None)` produces a Backtrader `bt.Strategy` subclass (`Bridge_default`) whose `params` are pre-wired with the market / instrument / instrument_code taken from the given `TradingContext`. The returned class bridges Backtrader's `next()`/`notify_order()`/`notify_trade()` callbacks into a platform-agnostic strategy (loaded from `strategy_code_dir` via `StrategyLoader`). Strategy classes are cached (keyed on strategy_name + market + instrument + instrument_code + strategy_code_dir + indicators_backtest_dir) and registered in the module namespace so they survive pickling under Optuna's `ProcessPoolExecutor`.

**Pass `strategy_code_dir` explicitly**: when omitted, the bridge falls back to reading it from the process environment (`PathsConfig.from_env().strategy_code_dir`), which is brittle inside library code paths — different invocations of the same process see whatever cwd / `ECHOLON_PROJECT_ROOT` happens to be set. Callers driving WFA, optimization, or anything multi-strategy should always pass an explicit `strategy_code_dir`.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.backtest.engine.backtrader_strategy import get_strategy_class
import backtrader as bt

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Recommended: explicit strategy_code_dir from your PathsConfig.
StrategyClass = get_strategy_class(ctx, strategy_code_dir="/path/to/workspace/strategy/baseline")

# 2. Per-slot loading (e.g. portfolio backtests with one bridge per slot).
StrategyClass = get_strategy_class(ctx, strategy_code_dir="/tmp/my_strategy")

# 3. Implicit (uses PathsConfig.from_env() internally) — works for the simple
#    single-process case where cwd / ECHOLON_PROJECT_ROOT happens to point
#    at the right workspace, but discouraged in library / WFA / multi-slot
#    contexts. Pass strategy_code_dir explicitly there.
StrategyClass = get_strategy_class(ctx)

# 3. Feed into Cerebro. The engine is injected separately via
#    strategy_params when EngineFactory / BacktestRunner call setup().
cerebro = bt.Cerebro()
cerebro.addstrategy(StrategyClass, engine=engine, strategy_params=params)
```

## When to use

- Inside Backtrader backtest setup when you need a pickle-safe strategy class bound to a ctx — typically via `BacktraderEngine.setup()` / `EngineFactory.create_backtest_engine(...)`, which call this internally.
- In WFA / Optuna optimization paths where the same class must be shared across worker processes (the cache + `__module__` assignment exist precisely to make pickling work under `ProcessPoolExecutor`).
- When loading a strategy from a non-default directory (e.g. per-slot code, hypothesis experiments), pass `strategy_code_dir` — the bridge uses `StrategyLoader` to import `strategy.strategy_main` and also scopes `strategy_indicator_metadata.json` to that slot.
- Do *not* instantiate `BacktraderStrategyBridge` directly. The params (market, instrument_code, strategy_code_dir) must be baked in via the subclass `type(...)` call this function performs.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `get_strategy_class(ctx, strategy_code_dir=None)` | `ctx: TradingContext`, optional path string to strategy code dir | `Type[bt.Strategy]` (cached) | Build or retrieve a `Bridge_default` class configured for the given ctx. Cache key: `{strategy_name}_{market}_{instrument}_{instrument_code}_{strategy_code_dir or 'default'}`. |

The returned class's `params` tuple (set via `type(...)`): `engine=None` (injected later), `strategy_name='default'`, `market`, `instrument` (full name, for metadata paths), `instrument_code` (for trading), `strategy_params={}`, `strategy_code_dir`, `printlog=True`.

Runtime behaviour of an instance of the returned class:
- `__init__` wires engine's `_market_data`, `_portfolio`, `_order_manager` to the Backtrader `self.data`/`self.broker` and calls `_register_indicators()` + `_initialize_strategy()`.
- `_register_indicators()` reads `load_indicator_metadata(ctx=ctx, metadata_path=...)` (per-slot when `strategy_code_dir` is set) and registers each indicator column from the data feed.
- `_initialize_strategy()` uses `StrategyLoader(strategy_dir).load_function("strategy", "strategy_main")` to obtain the platform-agnostic strategy factory and instantiates it with `trading_engine=engine, strategy_dir=<path>, **strategy_params`.
- Hooks: adds `ForcedExitStrategyHook` (interday futures) and/or `SessionAwareStrategyHook` (intraday) based on `market_adapter.has_contract_expiry` and `frequency_context.frequency_type`.
- Exceptions raised inside `self._agnostic_strategy.on_bar()` — which includes anything raised during the Template Method's `_execute_bar()` override (the canonical strategy-author override target) and any entry/exit/risk/sizer component callback it invokes — are translated to `BT-001` with bar/date/contract/position context by `_wrap_on_bar_exception`.

## Common errors

- **`BT-001` (from `echolon.errors`)** — raised by `_wrap_on_bar_exception` when the platform-agnostic strategy's `on_bar()` Template Method raises (typically from the strategy's `_execute_bar()` override, or from any entry/exit/risk/sizer component invoked by it). Context includes `bar_index`, `trading_date`, `contract`, `position_size`, `file` (strategy module), and `exception_repr`. See `echolon/native/errors/codes/BT-001.md`.
- **`FileNotFoundError: Strategy module not found: .../strategy.py`** — raised by `StrategyLoader.load_module` when the target directory is missing `strategy.py`. Most commonly an incorrect `strategy_code_dir` argument or an uninitialized workspace.
- **`AttributeError: Module 'strategy' ... has no attribute 'strategy_main'`** — the directory has `strategy.py` but it does not define `strategy_main`. Related: `STR-001`/`STR-002` if surfaced via `load_strategy_from_dir`'s preflight (direct `get_strategy_class` does not run preflight — it only calls `load_function`).
- **`TypeError` when Optuna pickles the strategy class** — if the cache key is bypassed or `__module__`/`__qualname__` overrides are stripped, pickling breaks. The function writes the class into `globals()[class_name]` specifically to keep pickle happy; do not delete from `_STRATEGY_CLASS_CACHE` mid-run.

## See also

- `engine_factory` skill — `EngineFactory.create_backtest_engine` calls `get_strategy_class` (indirectly via `BacktraderEngine.setup`).
- `strategy_loader` skill — performs the actual file-based loading of `strategy.strategy_main` inside `_initialize_strategy`.
- `trading_context` skill — source of `ctx.market_code`, `ctx.instrument_name`, `ctx.instrument_code` consumed here.
- `run_best_trial` skill — one common upstream caller via `BacktestRunner.best_trial`.
