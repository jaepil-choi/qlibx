# Frozen observation invocation scope

## Intent

One logical project invocation should verify each physical observation source once while retaining drift detection across invocations and defensive result isolation.

## Observable outcome

`ObservationStore.frozen()` is reentrant. The outer scope caches SHA-256 verification per physical source and fingerprint; outside a scope every query verifies as before. PIT filtering avoids an unnecessary full-frame copy, while returned frames remain defensive copies. One Project-owned store is shared by all data-consuming flows.

## Responsibilities and flow

Project catalog sessions enter the shared store's frozen scope. Direct flow users opt in explicitly by scoping their injected store. Cache state is cleared when the outermost scope exits.

## Alternatives and trade-offs

Process-lifetime hash caching was rejected because it would hide source drift between invocations. Returning internal frames was rejected because callers could corrupt later results.

## Validation

Observation tests prove nested in-scope queries hash once, out-of-scope queries hash every time, and drift outside a scope fails. `uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s; `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
