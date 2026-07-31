---
name: code-standards
description: Code quality rules for strategy components. Use when checking code standards, fixing quality issues, or validating logging compliance.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
---

# Code Standards Policy

## Section 1: No Error Handling

Strategy components MUST NOT contain error handling:

```python
# FORBIDDEN
try:
    value = self.params['key']
except KeyError:
    value = default

# FORBIDDEN
value = self.params.get('key', default)

# REQUIRED
value = self.params['key']  # Direct access only
```

## Section 2: Logging Compliance

Each component MUST log its output using type-specific methods:

| Component | Logging Method | Output Type |
|-----------|----------------|-------------|
| Entry | `self.log_entry_output(output)` | `EntrySignalOutput` |
| Exit | `self.log_exit_output(output)` | `ExitSignalOutput` |
| Risk | `self.log_risk_output(output)` | `RiskOutput` |
| Sizer | `self.log_sizer_output(output)` | `SizerOutput` |

## Section 3: Indicator Period Caps

Respect maximum periods to prevent NaN data:

| Indicator Type | Max Period |
|----------------|------------|
| TEMA, TRIX, ADXR | 62 |
| ADX, DEMA | 93 |
| Standard indicators | 180 |

## Section 4: Parameter Access

```python
# In __init__
self.adx_period = self.params['adx_period']
self.adx_threshold = self.params['adx_threshold']

# In methods - use extracted attributes
indicator_name = f'adx_{self.adx_period}'
if adx_value > self.adx_threshold:
    ...
```

## Section 5: Code Structure Rules

1. **No __init__.py Files**
   - Platform-agnostic components use relative imports
   - Creating __init__.py breaks `from entry import entry_rule` pattern
   - The file access hook blocks __init__.py creation

2. **400 Line Limit**
   - Keep components focused and under 400 lines
   - Use private helper methods for complex logic
   - Extract reusable patterns to separate methods

3. **Single Responsibility**
   - Entry, exit, risk, sizer MUST be separate components
   - Never combine entry and exit logic in one class
   - Each component handles one concern only

4. **Parameter Flow**
   - `strategy_params.py` → backtest scripts → BaseComponent → `self.params`
   - Never import strategy_params.py directly in components
   - Use `self.params['key']` not `DEFAULT_PARAMS['key']`

For complete validation checklist, see [VALIDATION_CHECKLIST.md](VALIDATION_CHECKLIST.md).
