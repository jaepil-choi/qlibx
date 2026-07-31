# Logging Rules Reference

## Component-Specific Logging Methods

Each component type has a dedicated logging method that enforces proper output format:

| Component | Logging Method | Output Type | Required Fields |
|-----------|----------------|-------------|-----------------|
| Entry | `self.log_entry_output(output)` | `EntrySignalOutput` | signal, strength, type, entry_reason, intent (regime optional — TRS-paradigm only) |
| Exit | `self.log_exit_output(output)` | `ExitSignalOutput` | should_exit, exit_reason, **position_size, bars_since_entry**, intent |
| Risk | `self.log_risk_output(output)` | `RiskOutput` | trading_allowed, risk_reason |
| Sizer | `self.log_sizer_output(output)` | `SizerOutput` | calculated_size, signal_direction, sizing_reason, raw_size |

## Single Output Pattern (CRITICAL)

**ALWAYS** create a single BaseModel instance for both logging and return:

```python
# CORRECT: Single instance for both
output = EntrySignalOutput(
    signal=signal,
    strength=strength,
    type=signal_type,
    entry_reason=reason,
    intent=intent
)
self.log_entry_output(output)  # Log same instance
return output                   # Return same instance

# WRONG: Separate dict for logging
log_data = {'signal': signal, 'strength': strength, ...}
self.log_component_output('entry', log_data)  # Different data!
return EntrySignalOutput(...)  # Different object!
```

## Required Fields by Component

### Entry Component
```python
output = EntrySignalOutput(
    signal='LONG',                 # Required: 'LONG' | 'SHORT' | 'HOLD'
    strength=0.85,                 # Required: float 0.0-1.0
    type='entry_long',             # Required: str
    entry_reason='TEMA crossover', # Required: str (non-empty)
    intent=OrderIntent.ENTRY_LONG, # Required when signal != 'HOLD'
    regime='trending_up',          # Optional: TRS strategies populate via self.get_market_regime();
                                   # TSMOM and other paradigms typically omit this field
    # Strategy-specific extras allowed
    rsi_value=45.2
)
```

### Exit Component
```python
output = ExitSignalOutput(
    should_exit=True,                       # Required: bool
    exit_reason='Stop hit',                 # Required: str (non-empty)
    position_size=abs(position.size),       # Required: float
    bars_since_entry=self.bars_in_position, # Required: int
    intent=OrderIntent.EXIT_LONG,           # Required when should_exit=True
    # Strategy-specific extras allowed
    pnl_pct=0.05
)
```

### Risk Component
```python
output = RiskOutput(
    trading_allowed=True,          # Required: bool
    risk_reason='Within limits',   # Required: str (non-empty)
    # Strategy-specific extras allowed
    current_drawdown=0.03
)
```

### Sizer Component
```python
output = SizerOutput(
    calculated_size=5,             # Required: int >= 0
    signal_direction='LONG',       # Required: 'LONG' | 'SHORT' | 'HOLD'
    sizing_reason='Risk-based',    # Required: str (non-empty)
    raw_size=5.7,                  # Required: float (pre-validation)
    # Strategy-specific extras allowed
    risk_amount=10000.0
)
```

## Validation at Instantiation

BaseModel validates fields at creation time with echolon catalog-coded errors:

```python
# This raises echolon catalog errors immediately (not generic Pydantic errors):
output = EntrySignalOutput(
    signal='INVALID',  # VAL-002: signal must be 'LONG' | 'SHORT' | 'HOLD'
    strength=1.5,      # ValidationError: > 1.0
    type='',           # ValidationError: empty string
    entry_reason='',   # VAL-001: missing required fields (if others omitted)
    intent=None
)
```

**Do NOT pre-validate** with an `if/raise` pattern before instantiation —
echolon's schema already does this via `_validate_signal_enum` (raises VAL-002
in `mode='before'`) and `_check_required_fields` (raises VAL-001 in
`mode='before'`). An extra pre-check duplicates work AND violates the No Error
Handling Policy (adds unnecessary defensive logic). Let the schema raise the
catalog-coded error; downstream tooling routes by code.

## Logging Diagnostics

Include strategy-specific diagnostic fields for analysis:

```python
output = EntrySignalOutput(
    signal=signal,
    strength=strength,
    type=signal_type,
    entry_reason=reason,
    intent=intent,
    regime=regime,
    # Diagnostic fields (via extra='allow')
    tema_short_value=tema_short,
    tema_long_value=tema_long,
    adx_value=adx,
    rsi_value=rsi,
    signal_count=self.signal_count
)
```

## Common Logging Errors

### Using Dict Instead of BaseModel
```python
# WRONG
self.log_component_output('entry', {'signal': 'LONG', ...})

# CORRECT
output = EntrySignalOutput(signal='LONG', ...)
self.log_entry_output(output)
```

### Missing Required Fields
```python
# WRONG - missing intent when signal != 'HOLD'
output = EntrySignalOutput(
    signal='LONG',
    strength=1.0,
    type='entry_long',
    entry_reason='Breakout',
    intent=None  # Should be OrderIntent.ENTRY_LONG!
)
```

### Logging Different Data Than Returned
```python
# WRONG - mismatch between logged and returned
log_output = EntrySignalOutput(signal='LONG', strength=0.8, ...)
self.log_entry_output(log_output)
return EntrySignalOutput(signal='LONG', strength=0.75, ...)  # Different!

# CORRECT - same instance
output = EntrySignalOutput(signal='LONG', strength=0.8, ...)
self.log_entry_output(output)
return output
```
