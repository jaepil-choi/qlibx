# 069 — Independent JSON Strategy state

## Why

PRD §§9.10-9.11 and `UC-STATE-001` require Strategy-owned state to advance without depending on an
order, fill or execution profile, to be returned at run end, and to cross run boundaries only when
the caller explicitly supplies it. The previous `StrategyMemoryStore` used versioned CAS commits
gated by Account feedback progression, so HOLD/no-order decisions and direct research could not
express the required state transition.

## Outcome

Strategy state is now one opaque strict JSON value. Direct and daily invocations accept an explicit
initial value, `StrategyView.strategy_state()` exposes it read-only, and a Strategy may return
`StrategyStateUpdate`. The Flow validates and advances the value immediately after a successful
Strategy return. Direct and daily results expose the final value; a fresh run never selects prior
state implicitly.

## Responsibilities and flow

- `strategy_state.py` defines recursive strict-JSON normalization, canonical fingerprinting,
  `StrategyStateUpdate`, and the read snapshot contract. Tuple/set, non-string mapping keys and
  non-finite floats fail with `MEMORY_NOT_JSON` before success publication.
- The update wrapper distinguishes no update from an intentional update to JSON `null`.
- `ResearchFlow` owns validation and promotion. It records a Strategy-state fingerprint only when
  the Strategy reads the state, then returns the normalized final value.
- `DailyExecutionFlow` threads that value between fired decisions and returns initial/final values.
  Feedback cursor remains Flow-owned Account feedback state and is not a state version.
- `StrategyResult` v4 and `SimulationCheckpoint` v4 carry the new lineage/state meaning. Strategy
  extension registration is v2. Stored composition requires exact v4 artifacts.
- The old `StrategyMemoryStore` and memory-commit evidence were removed. `account/memory.py` retains
  only legacy `MemorySnapshot` models needed to deserialize completed v2/v3 checkpoints for analysis.

## Ordering and failure semantics

State advances after Strategy calculation and before decision conversion or execution. Therefore a
later execution failure can leave a published Strategy result/proposed state while Account remains
unchanged. This divergence is intentional: Strategy state is decision memory, while Account is the
authority for committed market outcomes. Neither is silently reconciled into the other.

## Alternatives and trade-offs

Named state slots and package-owned migrations were rejected because they interpret the Strategy's
private schema. A durable latest-state selector was rejected because it would silently choose a
prior run and blur completed-run chaining with interrupted-run recovery. A feedback-coupled commit
was rejected because it directly violates zero-order and research-only state continuity.

## Validation

- Contract/traceability focus covering direct seed/read/write, invalid JSON, zero-order explicit run
  chaining, architecture, Strategy result/composition, extension and daily behavior: 71 passed in
  60.61s.
- Full acceptance: 31 passed in 130.22s. Converted scenarios verify Flow-owned feedback cursors and
  caller-owned explicit state seeding against actual Account outcomes.
- Full non-acceptance excluding performance: 252 passed; only the two pre-existing local data-audit
  drift tests failed (source SHA mismatch and sector rows 1,143,059 versus audited 187,615).
- Bundled daily/execution-convention/composition sample tests: 6 passed in 32.99s.
- `uv run ruff check src tests showcases`, `git diff --check`, wheel/sdist build and isolated wheel
  consumer imports passed.

## Remaining limitations

The package does not persist state across processes, choose the latest value, interpret Strategy
schemas, or migrate Strategy-owned JSON. Callers must store and explicitly supply the desired value.
