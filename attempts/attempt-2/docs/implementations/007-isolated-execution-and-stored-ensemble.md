# 007 Isolated execution and stored ensemble

## Intent

Implement the first M5 execution/composition slice for UC-EXEC-001, UC-ALPHA-CHILD-001,
UC-ARTIFACT-001, UC-ENSEMBLE-001, and the adaptive-memory boundary. One immutable parent decision
must be executable by isolated children; stored Strategy results must compose without importing or
rerunning their producers; and Strategy Memory may change only after confirmed Account feedback.

## Implementation

- `FrozenDecision` and `DailyExecutionFlow.execute_frozen` reuse an existing DecisionIntent
  artifact. Each child has its own Account, event identity, execution evidence, lineage, and
  checkpoint. No child changes the parent artifact or another child's state.
- `DailyExecutionProfile` can require an observed volume role. The Exchange participation policy
  then clips requested quantity and publishes the exact volume/lot diagnostics through the same
  pure cost and Fill path as the unrestricted child.
- `CompositionFlow` loads schema-versioned StrategyResult payloads from the artifact backend. Its
  ensemble operation records every ticker/member contribution, crossing, gross before and after
  netting, net exposure, residual budget, member lineage, and path-state identity.
- Fixed-budget netting that cannot retain the requested gross fails explicitly. Path-dependent
  members with different state/account/cursor identities fail before publishing a combined result.
- StrategyView exposes immutable Memory snapshots separately from Account state. A Strategy may
  propose a Memory update, but only Flow commits it after the Account feedback cursor advances and
  the expected Memory version matches. Checkpoints preserve Memory CAS and feedback authority.

## Real-data evidence

The acceptance uses the same bounded, unchanged A005930/A000660 rows extracted from
`data/DW/fng_stock_daily_prices.csv` as implementation record 006.

- Both children consume the same parent DecisionIntent artifact. The unrestricted child fills 129
  A005930 shares at the real 2024-01-03 close. The volume-constrained characterization child reads
  the real DW volume and fills 21 shares under a declared 0.000001 participation rate, reporting
  `VOLUME_LIMIT` and `LOT_ROUNDING`.
- Stored winner and opposite signed results each execute their producer once. Loading those
  artifacts later creates a fully crossed flexible ensemble: gross 1 before netting, gross 0 after
  netting, crossed gross 1, residual budget 1. The equivalent fixed-budget request fails.
- The first decision has feedback cursor zero and cannot update Memory. After committed Fill and
  Mark events advance actual feedback to cursor two, the next Strategy invocation proposes and
  Flow commits Memory version zero to one. Restored checkpoints retain the same CAS boundary.

## Trade-offs and limitations

This slice validates the Architecture's intraday/partial-fill **characterization seam** with real
daily volume, but it is not a true intraday market-data simulation: it has one next-session-close
execution event and no intraday quote path. It must not be labelled an intraday backtest. A
successful multi-event intraday profile still requires an intraday dataset fixture; the current
repository has no such source. Missing intraday bindings must fail rather than reuse daily close.

The ensemble supports StrategyResult members. A separate stored model-result contract remains a
later extension of the same typed loader boundary.

## Validation

- `uv run pytest -p no:cacheprovider ... -q`: 49 passed.
- `ruff check src tests`: passed.
- `git diff --check`: passed.
- `uv build`: built qlibx 0.1.0 sdist and wheel.
- Environment import smoke for qlibx, CompositionFlow, and DailyExecutionFlow: passed.
