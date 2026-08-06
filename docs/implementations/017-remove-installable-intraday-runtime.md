# 017 Remove installable intraday runtime

## Intent

Make the executable package match the current PRD support boundary. Intraday execution and partial
fill are future characterization, not current runtime capabilities. Hiding an implementation from
`qlibx.flow.__all__` is insufficient because users can still import `qlibx.flow.intraday` directly
from the built wheel and execute it.

## Implementation

- Remove `src/qlibx/flow/intraday.py` from production and therefore from future wheels.
- Retain the executor-neutral `DecisionIntent` boundary produced by the current real-DW daily flow.
- Replace the synthetic multi-event execution test with a future characterization proving that the
  parent intent has no selected execution profile while no `qlibx.flow.intraday` module or facade
  symbol is installable.
- Update the future YAML scenario to expect `unsupported`, no installable runtime, no daily
  fallback, and `current_support: false`.

This record supersedes the trade-off in implementation record 012 that retained an importable
intraday module. The later PRD scope explicitly classifies intraday/partial fill as future work, and
the current implementation plan requires unsupported capabilities not to appear as concrete runtime
operations.

## Trade-offs

The prior three-event Account-CAS experiment is removed from the production package. Its historical
implementation remains recoverable from Git and record 008, but it is not evidence of a supported
installed capability. A future intraday project must reintroduce an explicit data, liquidity,
scheduling, pending/cancel, and authority contract rather than promoting the old experiment.

Absence is used instead of adding a fake `unsupported` callable. A callable would itself become a
public-looking capability. Current daily results already record the full-fill/instant-settlement
limitations and do not route intraday requests to daily execution.

## Validation

- Future characterization, public contract, and registry -> 10 passed.
- Full pytest -> 78 tests passed in 48.25s.
- Ruff, public import/module smoke, and Git diff check -> passed.
- uv build -> built qlibx 0.1.0 sdist and wheel; wheel has 76 entries and zero intraday entries.
