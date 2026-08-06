# 008 Multi-event execution profile

## Intent

Complete the execution-scheduling half of M5 for UC-EXEC-001 and UC-ALPHA-CHILD-001. An
executor-neutral parent DecisionIntent must be reusable by a child that schedules several
point-in-time execution callbacks, commits each confirmed partial FillBatch independently, and
feeds the newest committed Account version into the next callback.

## Implementation

- ObservationStore and scoped views support an exact observation timestamp in addition to history
  and session queries. The mandatory `available_at <= callback_time` predicate remains in force.
- IntradayExecutionProfile declares point-price, volume, valuation, liquidity, and limitation
  semantics. It never falls back to a daily close binding.
- IntradayExecutionFlow resolves every binding and preflights every declared event/ticker/role
  before scheduling. Missing coverage therefore fails before Account mutation.
- Target quantities are frozen from the first event's price and the child Account's initial NAV.
  Each subsequent event computes only the remainder against the latest committed holdings. Each
  non-zero partial FillBatch uses Account CAS, and evidence records requested/dealt quantity,
  reasons, before/after versions, remaining target, completion, profile, and parent lineage.
- The terminal checkpoint preserves target quantities, completed event identities, and the full
  Account checkpoint so duplicate-event and version authority can be resumed.

## Fixture boundary

The repository contains daily/monthly data but no intraday source. The success fixture is therefore
an explicitly labelled three-row synthetic **contract characterization**, not historical execution
or market-quality evidence. It reuses the real-DW-derived A005930 parent DecisionIntent, then emits
09:30, 11:00, and 15:20 point observations with 30-share capacity at each callback.

The daily DW registration is also passed deliberately to the intraday profile. It fails with
`REQUIREMENT_NOT_RESOLVED` and leaves Account version zero, proving that unsupported granularity is
not silently reduced to a daily fill.

## Evidence

- The three callbacks read Account versions 0, 1, and 2 and commit 30 shares each.
- The target is 129 shares; final actual holding is 90 and explicit remainder is 39.
- The terminal Mark produces final Account version 4.
- Every execution/checkpoint artifact depends on the same immutable parent DecisionIntent.

## Trade-offs and limitations

This is a deterministic event/volume characterization, not an order-book simulator. There is no
latency, queue position, spread, auction, or endogenous market-impact model. Participation capacity
resets for each declared event. Those assumptions are serialized as profile limitations.

M5 still needs the UC-SIGNAL-002 stored model-result path; stored StrategyResult composition alone
does not satisfy that distinct scenario.

## Validation

- Real-DW parent plus synthetic multi-event acceptance: passed.
- Full pytest: 49 passed.
- Ruff and git diff --check: passed.
- `uv build`: built qlibx 0.1.0 sdist and wheel.
- Public import smoke for IntradayExecutionFlow and IntradayExecutionProfile: passed.
