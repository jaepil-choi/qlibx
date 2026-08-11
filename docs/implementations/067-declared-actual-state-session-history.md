# 067 — Declared actual-state session history

## Why

PRD `UC-ACCOUNT-HISTORY-001` requires a Strategy to read committed actual state as a bounded
session series or instrument panel without depending on Strategy memory. The previous runtime only
provided a current `AccountSnapshot` plus a raw commit-feedback window whose cursor was owned by
Strategy memory. It also exposed `Position.average_cost` and `realized_pnl` at runtime without
including those fields in the declared view/evidence contract.

## Outcome

A daily run can freeze the exact actual-state fields it will retain. A Strategy independently
declares account-series or instrument-panel requirements with an exact rows lookback and accesses
only those immutable projections. Missing recording fields fail before the first Strategy call,
Exchange call, or Account mutation. Successful results preserve selected fields, available session
range, and instruments as direct and inherited Strategy lineage.

## Responsibilities and flow

- `AccountHistoryRecordingSpec` is a user-owned frozen run input. Its empty default records no
  history; qlibx does not infer a hidden default.
- `ActualStateHistoryRecorder` is Flow-owned. After each successfully published session mark it
  projects only selected committed Account facts. Account-series `realized_pnl` and instrument-panel
  `realized_pnl` are session deltas derived from committed journal entries, not cumulative values
  relabeled as session results.
- A Strategy optionally declares `account_history_requirements()`. `DailyExecutionFlow._prepare()`
  validates every requested field against the frozen recording spec before scheduling mutation.
- `StrategyView.account_history(requirement_id)` returns a bounded immutable projection and records
  the exact consumed shape, fields, rows, available sessions, and instruments.
- `ResearchFlow` publishes those records as actual-account-history dependency edges. Canonical v4
  Strategy source lineage carries the additive records through later frozen composition.
- `AccountState.positions` now has a typed position protocol. `StateHolding` records current
  `average_cost` and per-position `realized_pnl`; older payloads without those additive fields
  deserialize them as unknown (`None`) rather than fabricating zero.

## Alternatives and trade-offs

A raw Account journal was rejected because the PRD selected session aggregation and because it
would expose write-model details to Strategy code. Recording every field by default was rejected:
recording cannot be reconstructed retroactively, and PRD §4.3.1 explicitly assigns field selection
to the user. A separate PIT cutoff was not added because every retained row is created only from
already committed Account outcomes at a session boundary.

The recorder currently lives in one process for one run and retains bounded selected values in
memory. This meets the current local simulation scope; a durable cross-run account-history backend
would be a separate product decision. Instrument-panel rows cover held instruments plus instruments
with realized PnL in that session. Missing post-exit average cost remains `None` rather than being
estimated.

## Validation

- Initial focused baseline before edits:
  `uv run pytest -q tests/test_public_daily.py tests/test_strategy_lineage.py tests/test_public_academic.py tests/test_catalog_recovery.py tests/test_document_traceability.py tests/test_architecture.py --basetemp <unique>`
  → `50 passed in 64.48s`.
- New public history and v4 lineage focus:
  `uv run pytest -q tests/test_public_daily.py::test_uc_account_history_001_uses_declared_history_without_strategy_state tests/test_public_daily.py::test_unrecorded_account_history_fails_before_strategy_or_account_mutation tests/test_strategy_lineage.py --basetemp <unique>`
  → `7 passed in 7.51s`.
- Daily, Strategy lineage, sizing, and constraint regression:
  `uv run pytest -q tests/test_public_daily.py tests/test_strategy_lineage.py tests/test_execution_sizing.py tests/test_portfolio_constraints.py --basetemp <unique>`
  → `35 passed in 43.51s`.
- `python -m ruff check` over all changed W1 source and tests → passed.
- `python -m compileall -q src/qlibx tests/test_public_daily.py` → passed.
- `git diff --check` → passed; Git emitted only the repository's configured LF-to-CRLF checkout
  warnings.

The ordinary first pytest attempt reached cleanup but failed with `PermissionError: [WinError 5]`
on the repository-local basetemp. Per the managed-Windows workflow, the exact failure was preserved
and later commands used unique ASCII cache/basetemp paths through the approved narrow boundary.

## Remaining limitations

Interrupted-run recovery removal and the independent JSON Strategy-state contract are recorded in
068 and 069. Architecture and current-support wording now describe the combined runtime.
