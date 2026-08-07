# Strategy result lineage and Ensemble migration

## Why this change exists

`strategy_result:v1` can record only one result-level `state_identity` and one
`feedback_cursor`. That shape cannot truthfully represent a Strategy or Ensemble that consumes
multiple frozen path-dependent Strategy results. The existing Ensemble special flow also loads
members directly, synthesizes one state identity, rejects a second distinct identity, and injects
manual dependencies outside `StrategyView` actual-access tracking.

The canonical requirement in `docs/qlibx-prd.md` requires producer-independent frozen result reuse,
no producer rerun, preservation of every source Account/Memory identity and cursor, and separation
between source alpha state and the current downstream execution Account.

## Intended outcome

- Persist the legacy payload under an exact `StrategyResultV1` reader.
- Publish new results under `strategy_result:v2` with canonical transitive source-state lineage.
- Resolve v1/v2 by exact artifact ID and envelope schema, never latest/first-compatible selection.
- Validate Strategy-declared direct path dependence against package-observed stateful accesses.
- Route Ensemble members through typed `StrategyView` artifact roles and compute once.
- Keep Daily recovery and Portfolio construction compatible with both stored versions.

## Responsibility changes

- `qlibx.operations.strategy` owns evidence-independent v1/v2 payload models, lineage invariants and
  the pure direct path-dependence rule.
- `LocalArtifactBackend` exposes exact envelope metadata without selecting or decoding a payload.
- `qlibx.flow.strategy_results` owns exact v1/v2 contract dispatch.
- `ResearchFlow` will own actual-access lineage promotion and v2 publication.
- `StrategyExtensionFlow` will apply the same direct path-dependence rule before registration.
- `CompositionFlow` will translate Ensemble member IDs into typed roles and bindings.
- Daily and Portfolio remain consumers of exact stored evidence; inherited lineage never becomes
  current mutable Account or Memory authority.

## Alternatives and trade-offs

- Reinterpreting v1 in place was rejected because existing consumers would silently assign a new
  meaning to the singular state fields.
- Selecting the latest compatible artifact was rejected because it would make frozen invocations
  non-reproducible.
- Guessing v2 then v1 was rejected in favor of one exact envelope metadata read.
- Marking incomplete legacy lineage as valid was rejected. Provenance-incomplete path-dependent v1
  results remain readable for ordinary recovery/Portfolio use but will fail compositional reuse.
- Mutable Ensemble caches and a second computation were rejected; an excluded transient exact-draft
  receipt will preserve one-computation evidence without serialized API drift.

## Validation evidence

Completed during the version-reader foundation:

Commit-scoped foundation subset: 32 passed in 30.91s.

```text
.venv/Scripts/python.exe -m pytest \
  tests/test_strategy_results.py tests/test_evidence.py \
  tests/test_strategy_artifact_inputs.py \
  tests/acceptance/test_recovery_scenarios.py \
  tests/test_public_daily.py tests/test_public_constraints.py \
  -q -p no:cacheprovider --basetemp .agent/tmp/pytest-m4-version-readers

53 passed in 220.89s
```

```text
.venv/Scripts/python.exe -m ruff check <M4 changed Python files>
All checks passed

git diff --check
clean
```

Final full-suite, build, wheel and installed smoke evidence will be appended before M4 completion.

## Remaining limitations and follow-up

- The version-safe reader foundation is complete, but ResearchFlow v2 promotion and Ensemble typed
  member migration still remain in this implementation record.
- `GAP-STRATEGY-COMPOSITION-001` remains open until M5 proves the installed producer-consumer-current
  Account vertical slice.
- Stored-signal CompositionFlow compatibility remains out of M4 scope.
