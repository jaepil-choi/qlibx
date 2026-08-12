# Checkpoint analysis authority

## Intent

Simulation analysis must derive total return from the run's authoritative initial account rather than infer initial NAV from execution artifacts.

## Observable outcome

Checkpoint schema v3 persists `initial_account`. Execution analysis inputs include event identity and time, are sorted before analysis, and produce order-independent fingerprints. Hold-only runs are valid; missing execution input fails only when the account journal proves fills occurred. The v2 checkpoint reader remains supported.

## Responsibilities and flow

Daily flow captures the initial account before events. Analysis loads the exact checkpoint schema, uses its initial NAV for v3, detects fills from the journal, and canonicalizes execution inputs and dependency IDs.

## Alternatives and trade-offs

Using the first fill as initial NAV was rejected because it makes hold-only analysis impossible and makes results depend on artifact availability and ordering.

## Validation

`uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s, including stored-analysis and daily checkpoint regressions. `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
