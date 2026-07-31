---
name: run_indicator_calculation
description: Calculates technical indicators for every contract in a TradingContext over a date range — wraps IndicatorProcessor, validates indicator_list via IndicatorList schema, and writes strategy_indicators.csv plus the metadata sidecar into output_dir.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.indicators.run.run_indicator_calculation

## Purpose

`run_indicator_calculation(ctx, output_dir, indicator_list, ...)` is the single orchestration entry for the indicator pipeline. It validates the `indicator_list` spec against `IndicatorList` (pydantic schema), maps the context's frequency to `"day"` / `"minute"` for the processor, ensures `output_dir` exists, loads trading dates from the calendar (or uses the explicit `start_date`/`end_date`), and delegates to `IndicatorProcessor(...).process_all_contracts(use_multiprocessing=...)` to calculate indicators for every contract and assemble the main-contract DataFrame. The result is also written to disk for `load_backtest_data` to pick up.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.indicators.run import run_indicator_calculation
from echolon.indicators import get_regime_optimizer
# (Echolon ships zero regime classifiers / optimizers. Your host application
# must call `register_regime_classifier(...)` and `register_regime_optimizer(...)`
# at session start before this code runs.)

ctx = MarketFactory.create(market="SHFE", instrument="cu", frequency="interday", bar_size="1d")

# 1. Minimal intraday call (no market_regime indicator → no regime_params needed).
df = run_indicator_calculation(
    ctx,
    output_dir="/path/to/indicators/al",
    indicator_list={
        "rsi":     {"timeperiod": [5, 14, 30]},    # Cartesian sweep
        "atr":     {"timeperiod": [14]},
        "ema":     {"timeperiod": [12, 26]},
    },
    start_date="2018-01-01",
    end_date="2024-12-31",
)

# 2. Interday call that needs regime_params (when indicator_list
#    contains "market_regime"). Optimize them first, then pass in.
regime_params = get_regime_optimizer("market_regime").optimize(
    df=None, n_trials=400, ctx=ctx,
)
df = run_indicator_calculation(
    ctx,
    output_dir="/path/to/indicators/cu",
    indicator_list={"rsi": {"timeperiod": [14]}, "market_regime": {}},
    regime_params=regime_params,
    start_date="2018-01-01",
    end_date="2024-12-31",
)

# 3. Provide explicit trading_dates instead of letting the calendar load them.
from datetime import datetime
dates = [datetime(2024, 1, d) for d in (2, 3, 4, 5, 8)]
df = run_indicator_calculation(
    ctx,
    output_dir="/tmp/debug",
    indicator_list={"rsi": {"timeperiod": [14]}},
    trading_dates=dates,
    use_parallel=False,     # easier debugging
)
```

## When to use

- Any time you need to (re)generate the `strategy_indicators.csv` that the backtest engine and `load_backtest_data` consume. Typical pipeline: `run_data_pipeline(ctx)` → `run_indicator_calculation(ctx, ...)` → backtest.
- When defining a new indicator — provide a flat `{name: {param: values}}` dict. Lists enable Cartesian sweeps (e.g. `{"timeperiod": [5, 14, 30]}` produces `rsi_5`, `rsi_14`, `rsi_30`). Empty dict `{name: {}}` uses the indicator's built-in defaults.
- When using `market_regime` on interday (daily-bar) data: pass a `regime_params` dict produced by `get_regime_optimizer("market_regime").optimize(df=None, n_trials=400, ctx=ctx)`. The host application is responsible for registering the matching classifier + optimizer beforehand (`register_regime_classifier(...)` + `register_regime_optimizer(...)`). Intraday regime handling uses `session_phase` + `volatility_state` instead and does not require this argument.
- Do *not* pass raw, unvalidated `indicator_list` dicts that don't match `IndicatorList`. The function calls `IndicatorList.model_validate(indicator_list)` for fail-fast validation; malformed specs raise a `pydantic.ValidationError` before any calculation runs.
- Do *not* omit both `trading_dates` and (`start_date`, `end_date`). The function raises `ValueError` when it has no way to derive the date list.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `run_indicator_calculation(ctx, output_dir, indicator_list, *, trading_dates=None, use_parallel=True, regime_params=None, start_date=None, end_date=None)` | `TradingContext`; `str` path; flat-dict indicator spec; optional list of datetimes; bool; optional dict; optional ISO strings | `pd.DataFrame` | Main-contract indicator rows. Empty DataFrame (with logger warning `[INDICATORS] Complete | no data returned`) if processing produces nothing. |
| Validation | — | — | `IndicatorList.model_validate(indicator_list)` — pydantic schema. Malformed spec → `ValidationError`. |
| Frequency mapping | — | — | `is_intraday → "minute"`, interday → `"day"` for the processor. |
| Date resolution | — | — | If `trading_dates is None`: `_load_trading_dates(market, instrument, start_date, end_date)` via `echolon.data.loaders.calendar_loader.get_trading_dates`. Requires both `start_date` and `end_date` when `trading_dates is None`. |
| Processor wiring | — | — | `IndicatorProcessor(ctx, trading_date_list, indicator_list, output_dir, regime_params, backtest_start_year)` then `processor.process_all_contracts(use_multiprocessing=use_parallel)`. `backtest_start_year` derived from `start_date[:4]` when `start_date` is provided. |

The processor writes `strategy_indicators.csv` and `strategy_indicator_metadata.json` into `output_dir`, plus sidecar `.warnings.json` files when columns have high NaN ratios (surfaced later as `IND-003` by `load_backtest_data`).

## Common errors

- **`pydantic.ValidationError` from `IndicatorList.model_validate`** — `indicator_list` is malformed. Inspect the error message for the offending key.
- **`ValueError: start_date and end_date are required when trading_dates is None.`** — must pass either `trading_dates` or both ISO date strings.
- **Downstream `IND-002`** — raised inside `IndicatorProcessor._resolve_function` when an indicator name in the JSON has no calculation mapping (typo, unknown name, or removed catalog entry). `IND-001` (casing) is raised by the strategy-side preflight against `get_indicator(...)` literals, not by this function. See `echolon/native/errors/codes/IND-001.md`, `echolon/native/errors/codes/IND-002.md`.
- **`IND-003`** — sidecar-only warning for high-NaN columns, surfaced later by `load_backtest_data`. See `echolon/native/errors/codes/IND-003.md`.
- **Silent empty DataFrame** — `IndicatorProcessor.process_all_contracts` returned no data (bad date range, missing contract files). Logger warning only; downstream `load_backtest_data` will then fail on a missing or empty CSV.

## Custom regime classifiers (extension point)

Echolon ships **no built-in regime classifiers**. The infrastructure
(`market_regime` indicator name, `get_market_regime()` accessor, classifier
registry, optimizer registry) is in place, but every classifier — TRS-style
rule-based, HMM, GMM, Carry term-structure, custom domain — must be
registered by your host application before any strategy code that calls
`self.get_market_regime()` runs:

```python
from echolon.indicators.protocols import RegimeClassifier
from echolon.indicators.registry import register_regime_classifier

class MyHMMClassifier:
    name = "hmm_3state"
    label_map = {0: "low_vol", 1: "med_vol", 2: "high_vol"}

    def fit_classify(self, df, params):
        # ... fit HMM and return numeric Series aligned to df.index
        return pd.Series(states, index=df.index)

register_regime_classifier(MyHMMClassifier())

# Now indicator_list can reference 'hmm_3state' — pipeline finds it
# via the registry.
```

See ``echolon.indicators.protocols.RegimeClassifier`` for the full
Protocol contract, and ``echolon.indicators.registry`` for
registration / lookup APIs (``register_regime_classifier``,
``get_regime_classifier``, ``list_classifiers``).

## See also

- `run_data_pipeline` skill — must run first to produce the contract CSVs this step reads.
- Regime optimizer (host-application-supplied) — produces the `regime_params` argument needed when `indicator_list` contains `market_regime` on an interday ctx. Register your optimizer via `register_regime_optimizer(...)` at session start; it is then accessible via `echolon.indicators.get_regime_optimizer("market_regime")`.
- `load_backtest_data`, `load_indicator_metadata` skills — downstream readers of this step's output.
- `trading_context` skill — supplies `ctx.market_code`, `ctx.instrument_name`, `ctx.is_intraday`.
- echolon docs: `echolon/indicators/schema.py` (`IndicatorList`), `echolon/indicators/engine/processor.py` (`IndicatorProcessor`), `echolon/indicators/protocols.py` (`RegimeClassifier`).
