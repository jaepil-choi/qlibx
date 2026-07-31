# Code Standards Validation Checklist

## Pre-Commit Checklist

### 1. No Error Handling
- [ ] No `try-except` blocks in strategy components
- [ ] No `.get()` with default values
- [ ] No fallback values or error recovery logic
- [ ] All dictionary access uses direct `['key']` syntax
- [ ] All errors propagate explicitly

### 2. BaseModel Usage
- [ ] All components return BaseModel instances (not Dict)
- [ ] EntrySignalOutput for entry components
- [ ] ExitSignalOutput for exit components
- [ ] RiskOutput for risk components
- [ ] SizerOutput for sizer components
- [ ] Attribute access (`.field`) not dict access (`['field']`)

### 3. Single Output Pattern
- [ ] ONE BaseModel instance created per method call
- [ ] Same instance used for logging AND return
- [ ] No separate Dict for logging

### 4. Logging Compliance
- [ ] Entry uses `self.log_entry_output(output)`
- [ ] Exit uses `self.log_exit_output(output)`
- [ ] Risk uses `self.log_risk_output(output)`
- [ ] Sizer uses `self.log_sizer_output(output)`

### 5. Indicator Naming
- [ ] Tier 1 indicators use `f'{name}_{self.period}'` format
- [ ] Tier 2 indicators use bare names only
- [ ] Tier 3 indicators use bare names only
- [ ] No hardcoded periods for Tier 1 indicators

### 6. Parameter Access
- [ ] Parameters extracted in `__init__` to `self.params`
- [ ] No `.get()` with defaults for parameter access
- [ ] Direct access: `self.params['key']`
- [ ] Extracted to instance attributes: `self.rsi_period = self.params['rsi_period']`

### 7. Position Sizer Specific
- [ ] Accepts `EntrySignalOutput` BaseModel (not Dict)
- [ ] Returns `SizerOutput` BaseModel (not int)
- [ ] Uses `signal_data.signal` (attribute access)
- [ ] Calls `self.validate_and_convert_position_size(raw_size)`
- [ ] Includes `raw_size` field in output

### 8. Indicator Period Caps
- [ ] TEMA, TRIX, ADXR periods <= 62
- [ ] ADX, DEMA periods <= 93
- [ ] Standard indicators <= 180

### 9. Code Structure Rules
- [ ] No __init__.py files in platform_agnostic/
- [ ] Each component under 400 lines
- [ ] Entry, exit, risk, sizer are separate components
- [ ] No direct import of strategy_params.py in components

### 10. State Management (Exit Components)
- [ ] Implements `_get_component_specific_state()` — returns all state needing persistence
- [ ] Implements `_restore_component_specific_state()` — restores state from dict
- [ ] Implements `_reset_state()` — resets per-trade state (stop prices, TP, bar counters, entry tracking)
- [ ] `_reset_state()` does NOT reset cross-trade state (consecutive_losses, circuit_breaker)
- [ ] `should_exit()` calls `self._reset_state()` when position is None or size == 0

## Quick Validation Commands

```bash
# Syntax check
python -m py_compile <file.py>

# Import check — use StrategyLoader (strategy code lives in arbitrary dirs;
# no fixed sys.path module path). Substitute the strategy_dir you are validating.
python -c "
from pathlib import Path
from echolon.strategy.loader import StrategyLoader
loader = StrategyLoader(Path('path/to/strategy_dir'))
for m in ('entry', 'exit', 'risk', 'sizer', 'strategy', 'strategy_params'):
    loader.load_module(m)
print('All component modules load cleanly')
"

# Check for try-except (should return nothing)
grep -n "try:" <file.py>
grep -n "except" <file.py>

# Check for .get() with defaults (should return nothing)
grep -n "\.get(" <file.py>
```

## Error Patterns to Fix

### Pattern 1: Try-Except Block
```python
# FORBIDDEN
try:
    value = self.params['key']
except KeyError:
    value = 10

# REQUIRED
value = self.params['key']
```

### Pattern 2: Get with Default
```python
# FORBIDDEN
value = self.params.get('key', 10)
data = bar.get('close', 0.0)

# REQUIRED
value = self.params['key']
data = bar['close']
```

### Pattern 3: Dict Return
```python
# FORBIDDEN
return {'signal': 'LONG', 'strength': 0.8}

# REQUIRED
return EntrySignalOutput(signal='LONG', strength=0.8, ...)
```

### Pattern 4: Dict Access on BaseModel
```python
# FORBIDDEN
signal = signal_data['signal']

# REQUIRED
signal = signal_data.signal
```

### Pattern 5: Hardcoded Indicator Period
```python
# FORBIDDEN
rsi = self.get_indicator('rsi_14')

# REQUIRED
rsi = self.get_indicator(f'rsi_{self.rsi_period}')
```

### Pattern 6: Wrong Logging Method
```python
# FORBIDDEN
self.log_component_output('entry', output_dict)

# REQUIRED
self.log_entry_output(output)
```

### Pattern 7: Separate Log and Return
```python
# FORBIDDEN
log_data = {'signal': signal}
self.log_entry_output(log_data)
return EntrySignalOutput(signal=signal, ...)

# REQUIRED
output = EntrySignalOutput(signal=signal, ...)
self.log_entry_output(output)
return output
```

## Automated Checks

Run these before committing. Set `STRATEGY_DIR` to your strategy-code directory first:

```bash
# Example strategy_dir values:
#   echolon scaffold:     export STRATEGY_DIR=workspace/strategy/baseline
#   echolon test fixture: export STRATEGY_DIR=echolon/tests/fixtures/baselines/aluminum_baseline
#   live deploy slot:     export STRATEGY_DIR=~/.dolphin/slots/<slot_id>/code
#   host iteration loop:  export STRATEGY_DIR=<whatever path your host app writes to>

# 1. No error handling patterns
! grep -rn "try:" "$STRATEGY_DIR/"
! grep -rn "except" "$STRATEGY_DIR/"
! grep -rn "\.get\s*(" "$STRATEGY_DIR/"

# 2. BaseModel returns (check for return statements)
grep -rn "return.*Output" "$STRATEGY_DIR/"

# 3. Proper logging methods
grep -rn "log_entry_output\|log_exit_output\|log_risk_output\|log_sizer_output" "$STRATEGY_DIR/"

# 4. Attribute access (not dict access)
! grep -rn "\['signal'\]" "$STRATEGY_DIR/"
! grep -rn "\['strength'\]" "$STRATEGY_DIR/"
```
