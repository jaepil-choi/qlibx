---
name: compute_indicators_from_frame
description: Computes the standard pipeline's per-bar indicators from a caller-provided continuous OHLCV DataFrame (block-bootstrap resamples, synthetic data) — no contract files, roll table, or disk I/O; identity with run_indicator_calculation away from main-contract rolls, hard-fails IND-009 on curve_carry names.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: frame_injectable_indicators
---

# echolon.indicators.run.compute_indicators_from_frame

## Purpose

`compute_indicators_from_frame(ohlcv, indicator_list, ctx, *, regime_params=None)` is the injectable-frame indicator entry point: it runs the SAME per-bar indicator computations `run_indicator_calculation` applies to its stitched main-contract series, but over a continuous OHLCV `DataFrame` the caller already holds in memory — block-bootstrap resamples, synthetic series, or any other caller-assembled frame — without touching contract files, the roll table, or any disk I/O. It validates `indicator_list` against the same `IndicatorList` pydantic schema, applies the same pre-compute normalization the per-contract path applies (`_prepare_ohlcv_frame`: missing open/high/low filled from that row's close, date conversion, chronological sort), and dispatches through the same compute path (`_compute_indicators_for_contract`), so column names and values follow the standard pipeline's rules. Returns a normalized copy of the input frame with one column appended per indicator/param-combo; the caller's frame is never mutated. Nothing is written to disk.

## Identity boundary — READ THIS BEFORE RELYING ON PARITY

The identity claim is precise, not blanket. The standard pipeline computes each contract's indicators over that contract's OWN full history and only then roll-selects rows per date; indicator computation itself is roll-blind. Consequences for a caller-provided continuous frame:

- **Reproduced (identical, ~1e-9 float tolerance):** every bar whose indicator lookback window falls entirely within one contiguous "same main contract" stretch of the series. For frames with no contract-roll structure at all (the usual bootstrap/synthetic case) that is every bar past warmup.
- **NOT reproduced — diverges near a main-contract change:** bars within `lookback − 1` bars after a roll date. The standard pipeline used the incoming contract's OWN pre-roll price history there; a bare continuous frame carries the outgoing contract's prices for those dates instead. This is inherent (the frame has no contract lineage), documented on the function docstring, and pinned by test (`tests/indicators/test_compute_from_frame.py` proves both the match zone and the divergence zone from a real two-contract roll fixture).
- **Not computable at all — hard-fails IND-009:** `curve_carry`-kind indicators (`carry_front_back`, `carry_z_3m`, …). They are built from the full multi-contract forward curve, which a single price series cannot supply. They are never silently dropped or approximated — the call raises before any computation. Either remove them from `indicator_list`, or compute them separately via `echolon.indicators.calculators.interday.carry.series_builder.build_carry_indicator_frame` and merge the columns yourself.
- **Regime classifiers — included but the semantics are on you:** a registered classifier name (e.g. `market_regime`) IS computed, via the same registry dispatch, and requires `regime_params` on an interday ctx exactly like `run_indicator_calculation`. On an **intraday** ctx, `regime_params` is forced to `None` — same behavior as `IndicatorProcessor` (intraday uses `session_phase` + `volatility_state`; regime_params unused) — so a caller-passed dict is ignored, not forwarded. The function does nothing to make classifier output meaningful on a synthetic frame: it classifies whatever series it is given. If your analysis needs regime columns held CONSTANT across resamples (the typical block-bootstrap requirement), recompute them once on your real data and carry them through — do not declare them here.

## Interface

```python
import pandas as pd
from echolon.config.markets.factory import MarketFactory
from echolon.indicators.run import compute_indicators_from_frame

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Typical bootstrap/synthetic use: continuous frame in, indicator columns out.
resampled = pd.DataFrame({
    "date":   pd.bdate_range("2020-01-02", periods=500),
    "open":   opens, "high": highs, "low": lows, "close": closes,
    "volume": volumes,
})
out = compute_indicators_from_frame(
    resampled,
    indicator_list={"rsi": {"timeperiod": [5, 14, 30]}, "atr": {"timeperiod": [14]}},
    ctx=ctx,
)
out["rsi_14"]   # same column-naming rules as the standard pipeline

# 2. Registered classifier on interday ctx — regime_params required,
#    same contract as run_indicator_calculation.
out = compute_indicators_from_frame(
    resampled,
    indicator_list={"rsi": {"timeperiod": [14]}, "market_regime": {}},
    ctx=ctx,
    regime_params=regime_params,   # from your registered optimizer
)

# 3. curve_carry names hard-fail (IND-009) — never silently dropped.
compute_indicators_from_frame(resampled, {"carry_front_back": {}}, ctx)
# -> raises IndicatorError code IND-009
```

## When to use

- Block-bootstrap / resampling analysis: you resample the continuous OHLCV the standard pipeline produced and need the identical indicator set recomputed on each resample, in memory, thousands of times — without re-running the file-based pipeline.
- Synthetic-data studies: indicator behavior on generated series that never had contract files.
- Do *not* use it as a shortcut replacement for `run_indicator_calculation` on real multi-contract data when roll-boundary bars matter to you — see the identity boundary above; the standard pipeline is the authority for the saved `strategy_indicators.csv`.
- Do *not* declare `curve_carry` indicators — the call hard-fails with IND-009 by design (see above for the two sanctioned alternatives).
- Do *not* expect a caller-passed `regime_params` to reach a classifier on an intraday ctx — it is forced to `None`, mirroring `IndicatorProcessor`.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `compute_indicators_from_frame(ohlcv, indicator_list, ctx, *, regime_params=None)` | `pd.DataFrame` (at minimum `open`/`high`/`low`/`close` + a `date` or `datetime` column); flat-dict indicator spec (same schema as `run_indicator_calculation`); `TradingContext`; optional dict | `pd.DataFrame` | Normalized copy of `ohlcv` + one column per computed indicator/param-combo. No `contract`/`contract_expiry`/`trading_date` metadata (a caller frame has no contract identity). Input frame not mutated. |
| Validation | — | — | `IndicatorList.model_validate(indicator_list)` — malformed spec → `pydantic.ValidationError` before any computation. |
| curve_carry guard | — | — | `_split_curve_carry` partitions by catalog kind; any `curve_carry` name → `raise_error("IND-009", indicators=...)` before any computation. |
| Intraday regime guard | — | — | `ctx.is_intraday` → `regime_params` forced to `None` (same routing as `IndicatorProcessor.__init__`). |
| Normalization | — | — | `_prepare_ohlcv_frame` (shared with `process_single_contract`): missing open/high/low ← close, `date` → datetime, sort by `datetime`/`date`, reset index. |
| Compute | — | — | `_compute_indicators_for_contract(df, indicator_list, ctx, regime_params, default_params=ctx.get_indicator_params(), session_availability=None)` — the standard pipeline's own compute path. |

## Common errors

- **`pydantic.ValidationError`** — malformed or empty `indicator_list`. Same fail-fast schema as `run_indicator_calculation`.
- **`IND-009`** — a `curve_carry` indicator was declared; a single continuous frame cannot supply the multi-contract forward curve. See `echolon/native/errors/codes/IND-009.md` for the two sanctioned fixes.
- **`ValueError: ... regime_params is None`** — a registered classifier name declared on an interday ctx without `regime_params` (raised by `_validate_regime_params`, same as the standard pipeline).
- **Downstream `IND-002`** — an indicator name with no calculator mapping (typo / unknown name), raised inside the shared compute path.
- **Silent semantic mismatch near rolls** — not an exception: if your frame embeds real main-contract rolls, bars within `lookback − 1` of a roll will NOT match the standard pipeline (see the identity boundary section). This is the one divergence that cannot be turned into an error because the frame carries no lineage to detect it with; it is the caller's responsibility to know whether their series contains rolls.

## See also

- `run_indicator_calculation` skill — the standard file-based pipeline this entry point mirrors; the authority for saved `strategy_indicators.csv`.
- `trading_context` skill — supplies `ctx.is_intraday`, `ctx.get_indicator_params()`, frequency routing.
- `echolon/native/errors/codes/IND-009.md` — the curve_carry exclusion, with worked example.
- `tests/indicators/test_compute_from_frame.py` — the load-bearing identity test (match zone + proven divergence zone from a real roll fixture).
- echolon code: `echolon/indicators/run.py` (`compute_indicators_from_frame`), `echolon/indicators/engine/processor.py` (`_prepare_ohlcv_frame`, `_compute_indicators_for_contract`, `_split_curve_carry`).
