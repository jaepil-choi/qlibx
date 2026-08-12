# 003 PIT direct Strategy research

## Why

Research results can look valid while silently consuming observations unavailable at the decision
time. qlibx therefore needs an enforced clock/view boundary before adding execution or Account
state.

## Outcome

BacktestClock accepts only aware timestamps and moves monotonically. ObservationStore rechecks the
registered physical fingerprint and applies available_at less than or equal to the frozen view time
on every query. StrategyView exposes only resolved semantic roles and records AccessRecord lineage.
ResearchFlow resolves requirements, invokes a direct Strategy, preserves fixed/flexible budget
semantics, and publishes a typed StrategyResult without touching authoritative state.

## Responsibility and flow

RequirementResolver decides whether declared inputs exist. ViewGate constructs the only data read
surface. Strategy calculates a draft but cannot access the raw store or artifact publisher.
ResearchFlow calculates exposure/residual evidence and publishes success or structured failure.
Registered datasets and frozen config are producer-independent dependency edges.

## Alternatives and trade-offs

M2 uses a frozen evaluation-time view rather than a full event queue; event callbacks belong to the
daily closed-loop slice. CSV reads remain simple and verify the full source hash on each query,
favoring correctness over throughput until a compiled/cache layer is introduced. Flexible budgets
retain residual cash and are never silently normalized.

## Validation

- Full pytest with task basetemp: 34 passed.
- Ruff over src and tests: passed.
- uv build: built qlibx-0.1.0 sdist and wheel.
- Fixtures verify future observation rejection, undeclared role rejection, source drift rejection,
  missing horizon failure before Strategy invocation, deterministic retry, and flexible residual.

## Remaining limitations

There is no Event queue, Executor, Exchange, Account, Memory, or closed-loop feedback. Observation
reads are not yet cached or column-pruned. Materialized model and stored-result composition remain
later slices.
