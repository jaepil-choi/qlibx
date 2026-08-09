# Empty feedback before Memory authority

## Intent

A Strategy without established Memory authority must not receive an implicit cumulative account-history window.

## Observable outcome

Before Memory initialization, `account_feedback()` returns an empty range at the current account cursor. A first memory commit may initialize from that empty range and persists the current cursor as authority. Established Memory continues to enforce bounded catch-up, CAS, and monotonic cursor advancement.

## Responsibilities and flow

Daily flow distinguishes the uninitialized `(version=0, value=None)` snapshot from established Memory. Only the former receives the empty current-cursor range and initialization semantics.

## Alternatives and trade-offs

Treating cursor zero as implicit authority was rejected because long memoryless runs would repeatedly expose cumulative history and couple otherwise stateless decisions to an unbounded journal.

## Validation

`uv run python -m pytest tests -q -p no:cacheprovider` passed 247 tests in 114.80s, including adaptive-memory, bounded-feedback, and public daily regressions. `uv run ruff check .`, the ignored `import qlibx` smoke script, and `uv build` also passed.
