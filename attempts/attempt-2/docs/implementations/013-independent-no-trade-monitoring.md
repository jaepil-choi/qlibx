# 013 Independent no-trade monitoring

## Intent

Implement PRD UC-EXEC-003 without coupling monitoring to a Strategy decision or execution event.
An independent clock must read a committed, fully marked Account snapshot and the PIT-visible K200
weight, then publish a constraint finding without changing Account or Strategy Memory.

## Implementation

- ConstraintMonitoringRequest carries only invocation and config identity. Monitoring time comes
  from the explicitly injected Clock rather than from a Strategy callback.
- MonitoringFlow resolves the declared benchmark-weight requirement, creates a MonitorView with one
  immutable Account snapshot, and records both dataset access and actual-state access.
- The pure monitor_actual_single_name_caps operation computes each held instrument's marked weight
  against max(single-name floor, benchmark weight). It emits no-short and single-name-cap findings.
- Incomplete valuation, non-positive NAV, missing benchmark coverage, and missing requirement
  bindings fail with CommitStatus.NONE before a success artifact is published.
- A successful constraint_monitoring_result has lineage to the config, exact Account
  version/feedback cursor, and the selected benchmark registration. The operation has no decision,
  order, Account commit, or Memory commit surface.

## Real-data evidence

The acceptance reads A000660 close prices from the bounded Parquet extracted unchanged from
data/DW/fng_stock_daily_prices.csv:

- 2024-01-04 close: 136,400 KRW.
- 2024-01-05 close: 137,500 KRW.

Cash is selected between nine times the two prices so one share moves from below 10% of marked NAV
to above 10% solely through the real price change. The real 2024-01-02 K200 weight is 6.74%, making
the active cap 10%. That K200 observation is visible from the user-confirmed next trading session,
2024-01-03 09:00 Asia/Seoul.

The missing-binding invocation fails without mutation. The successful no-trade invocation publishes
the cap breach, and an identical retry returns the same result and artifact identity. Account
checkpoint and an independent Strategy Memory checkpoint remain byte-for-byte equal before and
after monitoring.

## Trade-offs

Monitoring reuses the current MVP ConstraintDeclaration rather than introducing a second policy
model. This keeps adjustment, validation, and monitoring on one economic declaration while their
operations and artifacts remain separate.

The monitor records both passing and failing findings. That gives reporting a complete evaluated
set and avoids treating an absent finding as proof of compliance. It does not propose a corrective
trade; remediation remains a later user-selected decision workflow.

## Validation

- Monitoring, constraint, architecture, scenario, and real-data acceptance narrow suite -> 13
  passed.
- Full pytest -> 69 tests passed.
- Ruff, git diff check, and public import smoke -> passed.
- uv build -> built qlibx 0.1.0 sdist and wheel.
