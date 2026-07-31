---
name: trading-api-core
description: Platform-agnostic trading strategy API patterns. Use when generating entry, exit, risk, or sizer components, or when working with indicators and BaseModel outputs.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
---

# Trading API Core Patterns

## Indicator discovery — use the catalog, not this file

For indicator **existence / params**, use the echolon catalog tools — the
authoritative source that stays in sync with `ta_lib.py`:

- `list_indicators(has_lookback=None)` — all catalog names; optional filter on
  whether the indicator has a period-like parameter (sweepable single-dim
  lookback)
- `indicator_info(name)` — `{name, has_lookback, function, file, params}`
- `indicator_params(name)` — just the params list
- `validate_indicator_list(payload_json)` — validate a flat-dict
  `strategy_indicator_list.json` payload end-to-end
- `suggest_similar(name, limit=5)` — typo recovery

Available through two transports (same names + signatures + return shapes):

- **openai-agents SDK**: `echolon-mcp` stdio subprocess
- **LangGraph**: `lib/graph_util/indicator_tools.py::create_indicator_tools(ctx)`

Phase F-5 collapsed the previous 4-way `cluster` taxonomy
(`indicators_with_lookback` / `_without_lookback` / `_with_special_params` /
`intraday_context_indicators`) to a single derived boolean
`IndicatorInfo.has_lookback`. The runtime emits column names via
`processor._build_suffix` (`echolon/indicators/engine/processor.py`) — the
single source of truth for the resulting column-name shape, including
multi-param sweeps.

The naming sections below describe `get_indicator(name)` **runtime call
semantics** (what column name to pass at dispatch), not the on-disk
`strategy_indicator_list.json` wire format. The wire format is flat-dict:
`{"<name>": {"<param>": scalar | list}}`.

## Indicator Column Naming at get_indicator() (CRITICAL)

How the column name is built depends on what's swept in the JSON
declaration. The runtime computes the suffix via
`processor._build_suffix(combo, swept_keys)`:

### Swept single period (single-dim lookback sweep)

When the JSON sweeps exactly one period-like parameter
(`{"rsi": {"timeperiod": [10, 20]}}`), the runtime emits one column per
value with just the value as suffix: `rsi_10`, `rsi_11`, ..., `rsi_20`.
At lookup time:

```python
self.rsi_period = self.params['rsi_period']
rsi = self.get_indicator(f"rsi_{self.rsi_period}")
```

### Multi-param sweep (Cartesian)

When more than one param is a list, the runtime emits a column per
combination with a `keyN_value` suffix:

```json
{"bbands_upper": {"timeperiod": [10, 20], "nbdevup": [1.5, 2.0]}}
```

produces columns
`bbands_upper_timeperiod10_nbdevup1p5`,
`bbands_upper_timeperiod10_nbdevup2`,
`bbands_upper_timeperiod20_nbdevup1p5`,
`bbands_upper_timeperiod20_nbdevup2`.
(Float fractional parts encode `.` → `p`; integer-valued floats drop the `.0`.)

Lookup mirrors the suffix:

```python
col_suffix = f"timeperiod{self.bbands_timeperiod}_nbdevup{_format_indicator_param(self.bbands_nbdevup)}"
upper  = self.get_indicator(f"bbands_upper_{col_suffix}")
middle = self.get_indicator(f"bbands_middle_{col_suffix}")
lower  = self.get_indicator(f"bbands_lower_{col_suffix}")
```

Indicators with multiple outputs (BBANDS → upper/middle/lower; MACD →
line/signal/hist; STOCH → k/d) all share the same suffix per combo —
declare the *family* once in JSON, then look each output line up
separately in code.

The float-encoding rule lives in echolon's `processor._fmt`
(`echolon/indicators/engine/processor.py`). When you're authoring strategies
by hand or generating them upstream, mirror the same logic inline so the
lookup string matches what the runtime emitted:

```python
def _format_indicator_param(v):
    if isinstance(v, float):
        if v.is_integer(): return str(int(v))
        return str(v).replace(".", "p")
    return str(v)
```

### Scalar params or no params (no sweep)

When all params are scalars or there are no params
(`{"obv": {}}`, `{"bbands_upper": {"timeperiod": 20, "nbdevup": 2.0}}`), the
runtime emits the bare name: `obv`, `bbands_upper`. Lookup uses bare name:

```python
obv = self.get_indicator("obv")
upper = self.get_indicator("bbands_upper")
```

Use `indicator_info(name).has_lookback` to decide whether a sweepable
period is the right modeling choice for a given indicator.

### Market context — DO NOT access via `get_indicator`

`market_regime` and `session_phase` are stored as **numeric codes** at runtime.
Calling `self.get_indicator('market_regime')` returns an int — subsequent
`if regime == 'trending_up'` comparisons silently fail. Always use the
frequency-specific string-returning accessors:

- INTERDAY: `self.get_market_regime()` → label string from the registered
  classifier's `label_map`. Echolon ships zero classifiers — the host
  application registers one via
  `echolon.indicators.registry.register_regime_classifier(...)`. Without a
  registered classifier, this method raises. A typical TRS-style classifier
  might emit labels like
  `'trending_up'` / `'trending_down'` / `'ranging'` / `'volatile'`.
- INTRADAY: `self.get_session_phase()` → phase name (bar-size-dependent; see
  INTRADAY.md).

These methods raise `RuntimeError` if called in the wrong frequency context.

## BaseModel Output Pattern (CRITICAL)

All components MUST return Pydantic BaseModel instances:

| Component | Return Type | Required Fields | Optional |
|-----------|-------------|-----------------|----------|
| Entry | `EntrySignalOutput` | signal, strength, type, entry_reason | intent (required for non-HOLD), regime (TRS-paradigm; defaults to None per Phase A relaxation) |
| Exit | `ExitSignalOutput` | should_exit, exit_reason, position_size, bars_since_entry | intent (required when should_exit=True), signal (optional `Literal['LONG','SHORT','HOLD']`; echoes the originating entry signal when relevant) |
| Risk | `RiskOutput` | trading_allowed, risk_reason | — |
| Sizer | `SizerOutput` | calculated_size, signal_direction, sizing_reason, raw_size | — |

**Sizer MANDATORY Validation:**
```python
# MUST call before returning - validates non-negative integer
validated_size = self.validate_and_convert_position_size(raw_size)
```

**Access Pattern**: Use `.field` attribute access, NEVER `['field']` dict access.

**Single Output Pattern**:
```python
output = EntrySignalOutput(
    signal=signal,
    strength=strength,
    type=signal_type,
    entry_reason=reason,
    intent=intent,
    # Strategy-specific fields via extra='allow'
    rsi_value=rsi
)
self.log_entry_output(output)  # Log same instance
return output                   # Return same instance
```

### Catalog-Coded Validation Errors

The BaseModel schemas raise echolon catalog-coded errors (not generic Pydantic
errors) so the coding agent sees structured diagnostic fields:

- **VAL-001** — missing required field on output. Context includes the list of
  missing fields. Fix: add the missing fields to the instantiation.
- **VAL-002** — invalid signal enum value. Context includes the invalid value
  and the valid set `{LONG, SHORT, HOLD}`. Fix: use one of the valid enum
  strings.

Do NOT wrap output instantiation in `try/except pydantic.ValidationError` —
let catalog errors propagate so downstream tooling (validators, log analyzers,
debug agents) can route by code.

## No Error Handling Policy (CRITICAL)

- **NEVER** use try-except blocks
- **NEVER** use `.get()` with default values
- **NEVER** add fallback logic
- **ALWAYS** use direct access: `self.params['key']`

All errors must propagate explicitly for debugging.

## Component Interface Contracts

```python
# Entry component
class entry_rule(BaseComponent):
    def generate_signal(self) -> EntrySignalOutput: ...

# Exit component
class exit_rule(BaseComponent):
    def should_exit(self) -> ExitSignalOutput: ...

# Risk component
class risk_manager(BaseComponent):
    def can_trade(self) -> RiskOutput: ...

# Sizer component
class position_sizer(BaseComponent):
    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput: ...
```

For complete interface specifications, see [INTERFACES.md](INTERFACES.md).
For BaseStrategy class documentation, see [STRATEGY.md](STRATEGY.md).
For architecture overview, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Frequency-Specific Patterns

Strategies can be either **interday** (daily bars) or **intraday** (sub-daily bars).
The frequency is set on `TradingContext` at construction time (passed to `MarketFactory.create(...)`), and determines which hooks are applied.

| Frequency | Documentation | Key Features |
|-----------|--------------|--------------|
| Intraday | [INTRADAY.md](INTRADAY.md) | Session methods, VWAP, opening range, EOD close |
| Interday | [INTERDAY.md](INTERDAY.md) | Contract expiry, daily ATR, overnight gaps |

### Frequency-Agnostic Code Pattern (CRITICAL)

Session methods are only available in intraday mode. Use `hasattr()` guards:

```python
# CORRECT: Works for both frequencies
if hasattr(self, 'is_closing_phase') and self.is_closing_phase():
    # Intraday closing logic

# WRONG: Crashes in interday mode
if self.is_closing_phase():  # AttributeError!
```
