# Echolon Error Catalog

Each page documents one error code with what/why/fix plus a worked example
showing the typical LLM-author mistake. `EchelonError.docs_url` points here.

## Strategy structure (STR-*)
- [STR-001](STR-001.md): Missing required file
- [STR-002](STR-002.md): Class not found
- [STR-003](STR-003.md): Method not implemented

## Parameter framework (PRM-*)
- [PRM-001](PRM-001.md): Missing `printlog`
- [PRM-002](PRM-002.md): Params structure mismatch
- [PRM-003](PRM-003.md): Hardcoded parameter value in component logic
- [PRM-004](PRM-004.md): Defensive `.get()` on self.params
- [PRM-005](PRM-005.md): Optimized trial parameters could not be resolved
- [PRM-006](PRM-006.md): Parameter read via self.params['X'] but absent from DEFAULT_PARAMS
- [PRM-007](PRM-007.md): Search range drift between params_to_optimize.json and strategy_params.py
- [PRM-008](PRM-008.md): Param in params_to_optimize.json absent from optuna_search_space

## Component signal validation (VAL-*)
- [VAL-001](VAL-001.md): Missing required field
- [VAL-002](VAL-002.md): Invalid signal enum value
- [VAL-003](VAL-003.md): Required JSON key missing from expected artifact
- [VAL-005](VAL-005.md): Component method signature doesn't match protocol
- [VAL-006](VAL-006.md): Component method's return-type annotation is wrong

## Indicators (IND-*)
- [IND-001](IND-001.md): Name casing mismatch
- [IND-002](IND-002.md): Undeclared indicator
- [IND-003](IND-003.md): All-NaN column
- [IND-004](IND-004.md): Degenerate regime optimizer result
- [IND-005](IND-005.md): Calculator missing required OHLCV column
- [IND-006](IND-006.md): Inverted [min, max] sweep range
- [IND-007](IND-007.md): Component reads an undeclared indicator column
- [IND-008](IND-008.md): Legacy section-keyed indicator-list format
- [IND-009](IND-009.md): curve_carry indicator requested from the single-frame compute path

## Data loading (DAT-*)
- [DAT-001](DAT-001.md): Required OHLCV file not found
- [DAT-002](DAT-002.md): Corrupt state JSON
- [DAT-003](DAT-003.md): Main contract data missing
- [DAT-004](DAT-004.md): Empty calendar
- [DAT-005](DAT-005.md): Unsupported OHLCV frequency parameter

## Backtest (BT-*)
- [BT-001](BT-001.md): Strategy on_bar exception
- [BT-002](BT-002.md): Zero trades
- [BT-003](BT-003.md): Optuna constraint violation
- [BT-010](BT-010.md): Required log marker absent from backtest output

## Walk-Forward Analysis (WFA-*)
- [WFA-001](WFA-001.md): Zero valid trials across all windows
- [WFA-002](WFA-002.md): Incomplete WFA — some windows produced no robust trial

## Live (LIV-*)
- [LIV-001](LIV-001.md): Broker unavailable
- [LIV-002](LIV-002.md): Order rejected
- [LIV-003](LIV-003.md): QMT callback error

## Config (CFG-*)
- [CFG-001](CFG-001.md): end_date before start_date
- [CFG-002](CFG-002.md): Required directory missing
- [CFG-003](CFG-003.md): Required path config not injected
