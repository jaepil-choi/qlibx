---
name: parameter-patterns
description: Architecture doctrine for strategy parameters — ParameterSpec / ComponentParameterTemplate / StrategyParameterFramework shapes, ownership priority across entry/exit/risk/sizer, crossover constraint semantics, per-frequency indicator period caps. Complements generate_strategy_params (operational) with the conceptual "what and why" for the emitted code.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
---

# Parameter Architecture Patterns

> **Companion skill**: `generate_strategy_params` — the *operational* doc for
> the tool that emits `strategy_params.py`. This skill documents the
> *architecture* the tool targets. Both live next to the echolon code they
> describe.

## Parameter Flow

```
1. Strategy design documents → params_to_optimize.json
2. Upstream tool / agent calls the echolon-mcp `generate_strategy_params` tool
3. Echolon generator parses the JSON → emits strategy_params.py
4. Backtest / WFA / deploy load DEFAULT_PARAMS or Optuna-suggested params
5. Parameters passed to components via **params
6. Components extract to self.params in __init__
```

## ParameterSpec Structure

`echolon.strategy.parameter_architecture.ParameterSpec` — one per parameter in
each `ComponentParameterTemplate`:

```python
ParameterSpec(
    name="adx_period",
    param_type=ParameterType.INT,      # INT | FLOAT | BOOL | CATEGORICAL | FIXED
    default_value=14,
    min_value=10,
    max_value=20,                       # must respect indicator caps — see below
    description="ADX calculation period [SHARED with: exit, risk, sizer]"
)
```

Framework composition:

```python
framework = StrategyParameterFramework()
framework.register_component(EntryParameters())   # one ComponentParameterTemplate per component
framework.register_component(ExitParameters())
framework.register_component(RiskParameters())
framework.register_component(SizerParameters())
DEFAULT_PARAMS = framework.compose_default_strategy()
```

## Ownership Rules (CRITICAL)

Calculation parameters (indicator period params — typically names ending with
`_period`) must be owned by exactly **one** component. Sharing is expressed at
the owner's site; consumers reference the owner's Optuna suggestion.

**Ownership priority**: Entry → Exit → Risk → Sizer.

The first component in this sequence that uses a shared calculation parameter
owns it. Example: `adx_period` described as "SHARED by Entry, Exit, Risk, Sizing":

- **Owner**: Entry (first in sequence).
- `EntryParameters.define_parameters()` includes `adx_period` as optimizable.
- `Exit`/`Risk`/`Sizer` do NOT include `adx_period` as optimizable; instead
  they reference the owner's suggested value in `optuna_search_space`:
  ```python
  exit_params["adx_period"] = entry_params["adx_period"]
  ```

**Cross-name sharing** (e.g. `sizer_atr_period` shares `exit_atr_period`) is
declared in `params_to_optimize.json`'s `extraction_report.shared_parameters`
with entries like:
```json
{"param": "exit_atr_period → sizer_atr_period", "owner": "exit", "shared_by": ["sizing"]}
```

## Crossover Constraints

For short/long or fast/slow parameter pairs in Optuna, the generator emits a
pruning constraint to prevent identical periods (which cause zero-trade
scenarios):

```python
tema_short = trial.suggest_int("entry_tema_short_period", 10, 55)
tema_long  = trial.suggest_int("entry_tema_long_period", 20, 62)

if tema_long <= tema_short or (tema_long - tema_short) < 5:
    raise optuna.TrialPruned()
```

- **Period pairs** (names ending `_period`): require gap of **5** (prevents
  ambiguous crossover detection).
- **Non-period pairs** (multipliers, thresholds): require only `long > short`
  (no minimum gap).

## Indicator Period Caps (per frequency)

The generator auto-clamps over-cap period ranges; see the `generate_strategy_params`
skill for per-correction reporting semantics. Cap values, per frequency:

| Indicator tier | Interday (daily bars) | Intraday (sub-daily bars) | Rationale |
|---|---|---|---|
| TEMA / TRIX / ADXR | 62 | 500 | Triple-pass smoothing → ~3× effective lookback; large periods produce all-NaN columns |
| ADX / DEMA | 93 | 750 | Two-pass smoothing |
| Standard (all others) | 180 | 1000 | Conservative ceiling for single-pass indicators |

Declared in `echolon.config.indicator_config.IndicatorConfig`. Caller can inject
a custom `IndicatorConfig` to override. Applied only to params whose name ends
with `_period` — non-period params aren't cap-checked.

## Related

- **`generate_strategy_params`** — the echolon-mcp tool that consumes these rules
  deterministically. Read for the *how-to-call* + correction reporting.
- **`trading-api-core`** — how the emitted `strategy_params.py` is consumed at
  runtime (component `self.params` access pattern).
- **`optuna_optimizer`** — runs the emitted `optuna_search_space` function.

For the complete working file template, see `TEMPLATE.py`.

If the deterministic generator fails on a malformed `params_to_optimize.json` you cannot fix, the manual-composition fallback is to hand-write `strategy_params.py` against the structures in this skill — `ParameterSpec`, `ComponentParameterTemplate`, `StrategyParameterFramework`, `optuna_search_space` — using `TEMPLATE.py` as the starting point.
