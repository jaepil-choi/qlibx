# 066 — Strategy-owned decision trigger

## Why

The daily public profile stored exact `decision_times` in orchestration input. That made an economic
statement such as "rebalance every five eligible sessions" invisible in the Strategy and excluded
it from the Strategy-owned runtime identity. Showcase 004 also derived its session calendar from
complete price coverage, so a missing instrument observation could silently shift every later
decision date.

## Outcome

A Strategy may now choose a schedule-shaped trigger policy while the Flow retains callback and
Clock ownership. `EveryCandidate` is the default for Strategies with no trigger declaration, and
`EveryNSessions(n)` is the built-in periodic policy. Exact decision timestamps are no longer a
parallel public input. Showcase 004 will use a declared exchange-session calendar and fail
explicitly if the declared universe is incomplete on any session.

## Responsibility and flow changes

- `contracts/trigger.py` owns immutable `TriggerContext`/`TriggerDecision`, the `TriggerPolicy`
  protocol, and the two built-ins. Current policies have no data requirements or accesses.
- `TriggerAwareStrategyOperation` is a separate opt-in Protocol. Python Protocol members cannot be
  optional, so adding `trigger()` to `StrategyOperation` would have broken existing static
  implementations.
- `DailyExecutionFlow` schedules every supplied session close as a candidate, resolves the optional
  policy once, and evaluates it before Account, Memory, requirement, or View access. SKIP appends a
  deterministic trace entry and returns without publication or authority mutation. FIRE enters the
  unchanged `ResearchFlow.invoke_strategy()` path and adds a trigger dependency to the published
  Strategy result.
- The Flow hashes the policy fingerprint into the runtime effective config used by Strategy
  invocation, checkpoint, and recovery identity. It does not copy policy into
  `DailySimulationSpec`, because that would create a second cadence owner beside
  `strategy.trigger()`. Resume reconstructs FIRE history from completed and pending decision IDs;
  no new authoritative store or recovery field is introduced.
- `DailySimulationSpec.decision_times` was removed and its schema version advanced from 1 to 2.
  `FrozenDailyExecutionSpec` remains version 1 because its wire contract did not change.
- `DependencyEdge.dependency_kind` now admits `trigger` so FIRE evidence names the exact policy
  fingerprint with consumer role `decision_cadence`.

## Alternatives and trade-offs

Keeping `decision_times` as a deprecated option would preserve callers but create two conflicting
cadence authorities, so it was rejected. Copying a trigger model or fingerprint into the spec was
also rejected because caller and Strategy values could diverge. The selected runtime binding means
`DailySimulationSpec.frozen_config_fingerprint()` alone is the spec/environment identity; the
checkpoint's effective config fingerprint is the full spec/exchange/trigger identity.

Only schedule-shaped policies are current. Data arrival, price, fill-feedback, composite policies,
`TriggerView`, a generic scheduler, and a durable shared journal remain out of scope. Candidate
warmup is also separate: callers still choose an eligible calendar suffix, while the Strategy owns
the cadence applied within it.

## Validation

- `.venv\\Scripts\\python.exe -m ruff check src tests
  showcases\\show_004_two_strategy_data_flow` — passed.
- Focused contract/config/public daily suite — 27 passed.
- Pure trigger plus public daily suite — 18 passed after correcting the registered default-policy
  fixture.
- Trigger/public daily/recovery/registry/acceptance aggregate — 64 passed, 2 fixture failures in
  330.75s; both legacy v1 anchors lacked the new effective trigger identity.
- Corrected legacy v1 anchor rerun — 2 passed in 10.30s.
- Architecture/traceability rerun — 2 passed after removing a forbidden `contracts -> runtime`
  import discovered by the layer test.
- Full suite — 301 passed and 2 unrelated data-audit failures in 517.34s. Both failures report that
  the local `data/preprocessed/sector_classification.parquet` no longer matches the existing audit
  contract (1,143,059 actual rows versus 187,615 recorded rows, plus SHA-256 drift); neither the
  dataset nor its audit contract was changed for this task.
- Public import smoke test — passed for `qlibx` and every new trigger export.
- `uv build` — built `qlibx-0.1.0.tar.gz` and `qlibx-0.1.0-py3-none-any.whl`. The first attempt
  preserved a managed-Windows default-cache `WinError 5`; the successful attempt used a unique
  ASCII cache without deleting or mutating the default cache.
- Showcase 004 — two consecutive complete-data runs preserved 61 sessions/1,220 observations,
  Academic 8 decisions/160 fills/final NAV 110124723.71750417, and KRX 11 decisions/11
  executions/157 fill records/final cash 588983.2800000105 with identical terminal positions.
  `validate_missing_coverage.py` also passed by observing the explicit incomplete-coverage error.

## Remaining limitations and follow-up

- `docs/qlibx-prd.md` §9.8 still describes invocation-owned cadence. The user explicitly excluded
  PRD edits during implementation, so this record does not claim product-document alignment. The
  architecture and executable contract describe the implemented Strategy-owned schedule policy.
  **2026-08-11 note:** closed separately. §9.8 now states cadence as part of the Strategy's economic
  meaning and adds `UC-TRIGGER-001`.
- A Strategy that always returns `TARGET` under default `EveryCandidate` still needs a candidate
  calendar with a later eligible execution event or must return `HOLD` at the terminal candidate.
- Warmup readiness should later become an explicit typed Strategy outcome rather than hand-coded
  calendar slicing, but that is intentionally separate from schedule-shaped triggers.
- The architecture document's top-level statement that PRD always wins conflicts remains a separate
  product-governance decision and was not changed here.
