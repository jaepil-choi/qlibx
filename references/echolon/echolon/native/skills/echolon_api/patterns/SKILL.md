---
name: patterns
description: Five canonical strategy patterns (trend breakout, mean reversion, regime-switching, multi-timeframe, ML-signal) — when to use each, key idea, files to customize, sketch code, common errors. Use when proposing or comparing strategy shapes for a new idea.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: phase_f9b_docs_migration
---

# Patterns

Canonical strategy patterns in Echolon. Each pattern includes when to use it, the core idea, files to customize, and common errors.

## Indicator Naming Rules

1. **Column names are always lowercase.** `RSI` typed in JSON → `rsi_14`, `rsi_15`, ... in code (`IndicatorList` lowercases for you).
2. **Use `self.get_indicator('lowercase_name')`.** Uppercase raises `KeyError` from `market_data.get_indicator` (echolon/backtest/engine/backtrader_engine.py:196). Don't suppress it — let the error surface.
3. **Declare every indicator in `strategy_indicator_list.json`.** Undeclared indicators aren't pre-computed and the lookup will fail.
4. **Use the canonical catalog name.** Run `echolon indicators list` (or call `echolon.indicators.catalog.list_all()`) to see what's available. Common pitfalls: the rolling-extreme indicators are named `highest_high` / `lowest_low` (not `rolling_high` / `rolling_low` and not bare `high` / `low`).
5. **System / regime indicators are paradigm-specific.** `market_regime` is NOT a built-in indicator in echolon — it's emitted by a registered classifier. Strategies that need regime conditioning must have the host application register a classifier (typical pattern: a TRS-style regime classifier produces a numeric `market_regime` column with a `label_map`). Plain technical strategies don't need it.

See [IND-001](../../errors/codes/IND-001.md) for the casing-mismatch error (or call MCP `get_error_doc("IND-001")`).

## 1. Trend Breakout

**When to use:** Strong trending markets; instruments with persistent momentum (index futures, commodities in backwardation).

**Key idea:** Enter when price breaks above an N-bar rolling high (or below an N-bar rolling low for shorts). Exit on a trailing-low stop or opposite-direction break.

**Files to customize:**
- `entry.py` — compare `self.get_current_price()` to `self.get_indicator(f'highest_high_{self.lookback}')`
- `exit.py` — exit when close breaks the N-bar `lowest_low`
- `strategy_indicator_list.json` — declare `highest_high` and `lowest_low` with the periods you want swept

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    price = self.get_current_price()
    upper = self.get_indicator(f"highest_high_{self.lookback}")
    if price > upper:
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="breakout",
            entry_reason=f"Close {price} > {self.lookback}-bar high {upper}",
            intent=OrderIntent.ENTRY_LONG,
        )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason="No breakout")
```

See `echolon/native/templates/momentum_breakout/` for the full working version (or `echolon examples copy momentum_breakout <dest>`).

**Common errors:** IND-001 (uppercase `HIGHEST_HIGH` in code). If you forget to declare `highest_high` in JSON, the runtime call raises `KeyError` from `get_indicator`, which surfaces as BT-001 inside a backtest bar — not as IND-002. (IND-002 only fires when the JSON itself names an indicator the catalog doesn't know.)

## 2. Mean Reversion

**When to use:** Range-bound markets; instruments that oscillate around a mean (pairs, yield curve spreads, some FX crosses).

**Key idea:** Enter when an oscillator crosses an oversold/overbought threshold. Exit when it reverts to neutral.

**Files to customize:**
- `entry.py` — check `self.get_indicator(f"rsi_{period}")` < 30 (oversold)
- `exit.py` — exit when RSI > 50 or a bars-held cap is reached
- `strategy_indicator_list.json` — declare `rsi` at your chosen period

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    rsi = self.get_indicator(f"rsi_{self.rsi_period}")
    if rsi < self.oversold_threshold:
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="oversold",
            entry_reason=f"RSI={rsi} below {self.oversold_threshold}",
            intent=OrderIntent.ENTRY_LONG,
        )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason="Not oversold")
```

See `echolon/native/templates/rsi_mean_reversion/` for the full working version (or `echolon examples copy rsi_mean_reversion <dest>`).

**Common errors:** PRM-001 (missing `printlog` in `entry_params`), VAL-002 (using `BUY` instead of `LONG`).

## 3. Regime-Switching

**When to use:** Strategies that must behave differently based on market condition — e.g., momentum in trending regimes, mean reversion in ranging.

**Prerequisite:** A regime classifier registered with echolon. Echolon ships with no built-in classifier — your application must register one via `echolon.indicators.registry`. The classifier provides a `label_map: dict[int, str]` that converts the numeric `market_regime` indicator into string labels, plus the actual computation that emits the column.

**Key idea:** Branch the entry/exit logic on `self.get_market_regime()`. The labels returned depend on the registered classifier. A typical TRS-style classifier might emit `trending_up`, `trending_down`, `ranging`, `volatile`.

**Files to customize:**
- `entry.py` — outer `if regime == "trending_up"` branches
- `strategy_indicator_list.json` — add `"market_regime": {}` to the flat-dict
- `strategy_params.py` — define per-regime thresholds (e.g., `trend_threshold`, `range_threshold`)
- Application bootstrap — register your classifier at startup before any strategy code runs

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    regime = self.get_market_regime()
    price = self.get_current_price()
    if regime == "trending_up":
        upper = self.get_indicator(f"highest_high_{self.trend_lookback}")
        if price > upper:
            return EntrySignalOutput(
                signal="LONG", strength=1.0, type="trend_break",
                entry_reason="Trending regime breakout",
                intent=OrderIntent.ENTRY_LONG,
                regime=regime,
            )
    elif regime == "ranging":
        rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        if rsi < 30:
            return EntrySignalOutput(
                signal="LONG", strength=1.0, type="range_revert",
                entry_reason="Range oversold",
                intent=OrderIntent.ENTRY_LONG,
                regime=regime,
            )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason=f"No signal in {regime}",
                             regime=regime)
```

**Common errors:** missing classifier registration — `get_regime_classifier('market_regime')` raises before the strategy ever runs if no classifier was registered. Forgetting to declare `market_regime` in JSON surfaces at backtest time as a `KeyError` from `get_indicator('market_regime')` (wrapped as BT-001), not as IND-002.

## 4. Multi-Timeframe

**When to use:** Intraday execution informed by a higher-timeframe bias (e.g., take long signals only when daily EMA is rising).

**Key idea:** Pre-compute the higher-timeframe indicator at daily frequency, then expose its last value to each intraday bar via the indicator pipeline. The strategy code sees a single indicator column; resampling is done upstream.

**Files to customize:**
- `strategy_indicator_list.json` — declare both timeframes' indicators (the daily-resampled column is supplied by your data pipeline; pick a name your pipeline emits)
- `entry.py` — gate signals on the daily indicator before checking intraday triggers

**Sketch (assumes `ema_daily_50` is supplied by your data pipeline as a daily-resampled column on the intraday frame):**

```python
def generate_signal(self) -> EntrySignalOutput:
    daily_ema = self.get_indicator("ema_daily_50")
    intraday_ema = self.get_indicator(f"ema_{self.fast_period}")
    price = self.get_current_price()
    long_bias = price > daily_ema
    if long_bias and price > intraday_ema:
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="mtf_pullback",
            entry_reason="Above daily EMA and intraday EMA",
            intent=OrderIntent.ENTRY_LONG,
        )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason="No MTF alignment")
```

**Common errors:** DAT-001 (daily data file missing), or a `KeyError` from `get_indicator("ema_daily_50")` if the column isn't pre-emitted by your pipeline (surfaces as BT-001 inside a backtest bar). IND-002 fires only if your `strategy_indicator_list.json` itself names an indicator echolon's catalog doesn't know. Note: `ema_daily_50` is illustrative — echolon's catalog only contains single-timeframe `ema`. Multi-timeframe columns must come from your data pipeline as pre-emitted columns.

## 5. ML Signal

**When to use:** You have a trained model that outputs a directional score from a fixed feature vector.

**Key idea:** Load the model once in `__init__`. In `generate_signal()`, build the feature vector from `self.get_indicator(...)` calls, call `model.predict_proba`, and threshold the output. Use whatever serialization format your training pipeline produced (ONNX, joblib, native framework formats); load it with the matching loader. Be careful loading binary model formats from untrusted sources — they can execute arbitrary code on load.

**Files to customize:**
- `entry.py` — `__init__` loads the model; `generate_signal` builds features and predicts
- `strategy_indicator_list.json` — declare every feature the model expects
- `strategy_params.py` — expose the probability threshold as a tunable parameter

**Sketch (loader and feature set are pseudocode — substitute your model's actual loader):**

```python
import numpy as np
from pathlib import Path

class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.model = load_model(Path(self.params["model_path"]))  # your loader
        self.prob_threshold = self.params["prob_threshold"]

    def generate_signal(self) -> EntrySignalOutput:
        features = np.array([[
            self.get_indicator("rsi_14"),
            self.get_indicator("atr_14"),
            self.get_indicator("ema_20"),
        ]])
        prob_long = float(self.model.predict_proba(features)[0, 1])
        if prob_long > self.prob_threshold:
            return EntrySignalOutput(
                signal="LONG", strength=prob_long, type="ml_long",
                entry_reason=f"p(long)={prob_long:.3f}",
                intent=OrderIntent.ENTRY_LONG,
            )
        return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                                 entry_reason="Below threshold")
```

**Common errors:** DAT-001 (model file missing), `KeyError` from `get_indicator(...)` if a feature column isn't declared in JSON (surfaces as BT-001 at backtest time), PRM-002 (`model_path` missing from `entry_params`).
