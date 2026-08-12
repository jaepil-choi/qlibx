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
- `ResearchFlow` owns actual-access lineage promotion, dependency-key conflict checks, v2 publication,
  and a package-owned typed computation-error boundary.
- `StrategyExtensionFlow` applies the same direct path-dependence rule before registration.
- `CompositionFlow` translates Ensemble member IDs into typed roles and bindings.
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

Version-reader and recovery checkpoints:

```text
foundation and exact-reader subsets: 53 passed in 220.89s
commit-scoped foundation subset: 32 passed in 30.91s
Daily and recovery subset: 21 passed in 178.73s
```

Promotion, extension-parity and Ensemble checkpoints:

```text
lineage and extension core: 33 passed in 30.91s
generic and Ensemble paths: 31 passed in 47.30s
M3 parity and Ensemble paths: 27 passed in 46.50s
final typed-error and dependency-key subset: 29 passed in 17.39s
```

The first complete-suite run exposed nine test Strategies that read package-observed state while
still declaring `path_dependent=False`. Their fixtures were corrected to state their real contract;
production code did not add a compatibility fallback. The exact failed scenarios then passed 16
checks. The final complete suite passed:

```text
UV_CACHE_DIR=D:\chljeffreyz\DevProjects\qlibx\.uv-cache-m4 \
  uv run pytest -q --basetemp C:\tmp\qlibx-m4-final-full-20260807

231 passed in 111.14s
```

```text
uv run ruff check .
All checks passed

git diff --check
clean

UV_CACHE_DIR=D:\chljeffreyz\DevProjects\qlibx\.uv-cache-m4 uv build
Successfully built dist\qlibx-0.1.0.tar.gz
Successfully built dist\qlibx-0.1.0-py3-none-any.whl
```

Ruff emitted only the pre-existing access-denied warnings for ignored `.agent/tmp` pytest scratch
directories. The build initially reproduced the managed-Windows default-cache access denial and a
sandboxed network denial; the documented task-scoped ASCII cache plus approved network boundary
completed the same build. Archive inspection found every changed production module in both wheel
and sdist.

A fresh Python 3.12 environment installed only the built wheel. Outside the source checkout it
published a legacy `strategy_result:v1`, consumed it through a typed Strategy artifact role,
published `strategy_result:v2`, and consumed that exact v2 artifact through the migrated Ensemble
path. The smoke completed with `wheel-smoke: v1-load -> v2-publish -> typed-ensemble passed`.

## Remaining limitations and follow-up

- `GAP-STRATEGY-COMPOSITION-001` remains open until M5 proves the full installed
  producer-consumer-current Account execution slice. M4 proves the library mechanisms, not that
  complete installed workflow.
- Provenance-incomplete path-dependent v1 artifacts remain readable by recovery and Portfolio but
  are intentionally rejected for compositional lineage promotion.
- Stored-signal CompositionFlow compatibility remains unchanged and outside M4 scope.
