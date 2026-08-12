# 035 Extract pure order sizing and session performance

## Intent

`DailyExecutionFlow` owned execution-session sizing arithmetic and session return reconciliation in
addition to callback ordering, state commit and artifact publication. The calculations could only be
tested through a full clock-driven run, allowing a session-price bug to survive the suite and making
monitoring arithmetic an authority-bearing side effect.

## Observable outcome

Order sizing is a deterministic execution operation over a frozen request and account-state record.
Session performance is a deterministic analysis operation over committed opening, execution and
closing evidence. Daily flow resolves inputs, invokes those operations, then retains exclusive
ownership of exchange calls, Account commits and artifact publication.

A missing mark no longer fails the run from an observer callback. Monitoring continues with
`session_performance_status="skipped_missing_mark"`; existing monitor artifacts load with the
`"published"` default.

## Responsibilities and flow

- `size_session_orders` calculates NAV from execution-session prices, reports missing prices and
  invalid NAV through `SizingError`, preserves the `1e-12` dead band, and returns sell-first then
  alphabetical immutable orders.
- `compute_session_performance` calculates turnover, cost rate, gross return and portfolio return.
  Pydantic reconciliation failures become `SESSION_PERFORMANCE_NOT_RECONCILED`.
- `SessionPerformanceEvidence` moved from flow to analysis with exactly the same fields and order.
  `qlibx.flow` continues to re-export the same class and recovery uses it as the artifact model.
- `DailyExecutionFlow` only translates operation failures, matches orders, commits state and
  publishes evidence. `SESSION_SOURCE_ARTIFACT_MISSING` remains a flow-level lineage check.

## Alternatives and trade-offs

Decomposing the entire 1,700-line flow into callback classes was rejected as unnecessary risk for
this remediation. Only the two independently testable calculations moved. Passing mutable Account
objects into execution was rejected; `StateAccessRecord` is a frozen projection of the same sparse
positions used by `AccountSnapshot.holdings()`.

Using `account_state.nav` for sizing was rejected because it is based on prior marks. Quantity
conversion deliberately uses current execution-session prices and the selected sizing role.

## Validation

```
.venv/Scripts/python.exe -m pytest tests/test_execution_sizing.py tests/test_analysis_sessions.py tests/test_public_daily.py tests/acceptance/test_execution_scenarios.py -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c4-targeted-019fd96d
-> 30 passed in 123.68s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c4-full-019fd96d
-> 163 passed in 398.43s

.venv/Scripts/python.exe -m pytest tests/test_execution_sizing.py tests/test_analysis_sessions.py -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c4-final-019fd96d
-> 13 passed in 0.61s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!

git diff --check
-> clean
```

The legacy golden JSON was emitted by the pre-move model. The post-move artifact contract loads and
re-serializes it byte-for-byte, including field order.

## Remaining limitations

- `DailyExecutionFlow` remains a large orchestration class. Callback-class decomposition is outside
  this remediation.
- Missing mark evidence is observable only through the monitor status; it does not synthesize a
  performance record.
- The pure sizing operation supports the current long-only weight-to-share conversion. Short and
  derivative quantity semantics remain future capabilities.