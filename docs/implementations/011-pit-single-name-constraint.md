# 011 PIT single-name constraint

## Intent

Implement the current PRD hard-constraint slice after the user confirmed that K200 membership and
sector observations become usable at 09:00 Asia/Seoul on the next trading session. The selected
constraint workflow must fail on missing or not-yet-available benchmark weights, preserve
best-effort adjustment residuals, and validate execution eligibility independently.

## Implementation

- `tests/scenarios/data_sources.yaml` records the user-confirmed availability rule for K200 and
  sector data while continuing to reject the pre-existing generated `available_at` columns.
- The real-data fixture derives the next trading session from distinct K200 observation dates and
  materializes that date at 09:00 Asia/Seoul. It does not add one calendar day.
- `ConstraintDeclaration` exposes only the current MVP hard constraints: no-short and
  $w_i \le \max(10\%, w_i^{index})$. The benchmark weight is an invocation-time requirement.
- `ConstraintFlow.adjust` loads an immutable portfolio artifact, resolves and reads PIT benchmark
  weights, performs continuous clipping, applies the same order-delta lot floor used by Exchange,
  and publishes original/continuous/adjusted weights with before and unresolved excess.
- `ConstraintFlow.validate` reloads the adjustment artifact, independently resolves and reads the
  benchmark, rejects declaration/cutoff mismatches, and publishes pass/deny findings. A completed
  adjustment is not treated as execution eligibility.
- Missing registration and hidden benchmark rows publish immutable failure evidence with
  `CommitStatus.NONE`; neither operation has Account or Memory authority.

## Real-data evidence

The acceptance uses K200 membership and daily prices reconciled against the repository DW files.
The 2024-01-02 K200 observations for A005930 and A000660 are materialized with
`available_at=2024-01-03 09:00 Asia/Seoul`.

- With no benchmark registration, adjustment fails with `REQUIREMENT_NOT_RESOLVED`.
- At the 2024-01-02 close, the registered observation remains hidden and adjustment fails with
  `CONSTRAINT_BENCHMARK_COVERAGE_MISSING`.
- At the 2024-01-03 close, A005930's actual benchmark weight is 31.72%, so its cap is 31.72%.
- From an explicit 12-share pre-trade holding, a continuous 31.72% target at the real 77,000 price,
  one-share lot, and 970,000 NAV requests a sale of 8.003 shares. Exchange-compatible lot flooring
  sells 8 shares and leaves four shares or 31.752577%. The adjustment artifact records the positive
  residual breach and the immutable pre-trade state identity.
- Independent validation completes but sets `eligible=false` and reports the same cap excess.
- A separate contract test verifies that a negative signed target is adjusted to zero and then
  passes independent no-short validation.

## Alternatives and trade-offs

A generic next-session registration rule was not added. The public registration contract already
accepts an explicit `available_at` field, and deriving a calendar-aware value belongs in the
user-confirmed data preparation step. Adding a calendar registry and rule engine for one fixture
would create an unnecessary second time authority.

Sector availability is recorded using the same confirmed rule, but sector constraint execution is
not implemented because the current PRD identifies no-short and the time-varying single-name cap as
the only MVP hard constraints. Sector constraints remain future work.

Order-delta lot flooring is explicit and deterministic but is not an optimizer. It may leave cash
or a small constraint breach; those outcomes are evidence for the independent validator, not
silently redistributed weights.

## Validation

- `uv run pytest ... tests/test_portfolio_constraints.py ...` -> 9 passed.
- `uv run pytest -p no:cacheprovider ... -q` -> 65 passed in 36.89s.
- `uv run ruff check .` -> passed.
- Public import smoke for `ConstraintFlow` and `ConstraintDeclaration` -> passed.
- `uv build` -> built qlibx 0.1.0 sdist and wheel.
