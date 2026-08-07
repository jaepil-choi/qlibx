# Reduce catalog and observation access costs without weakening recovery or PIT integrity

Status: complete

## Purpose

Reduce local catalog connection/recovery overhead and repeated observation frame reads while preserving append-only publication, crash recovery, typed failures, physical fingerprint checks, and PIT filtering.

## Scope and non-goals

In scope: reproducible performance harness, bounded recovery parsing, one backend per QlibxProject, explicit catalog sessions, session conflict documentation, and instance-local observation frame caching. Out of scope: publication phase reduction, event-order sequences, information_schema replacement, global connections/caches, xdist, database schema migration, staging/committing/pushing.

## Acceptance criteria

- Current full suite remains green; baseline is 231 passed in 469.68s on HEAD ce15634.
- Unknown publication event schema still blocks audit and publication without mutation.
- At 800 publishes, final bucket cost is at most 1.5x the first bucket on the same machine and tree.
- Scoped sessions reduce catalog connect/close counts while all catalog recovery/concurrency tests pass.
- Observation cache reduces source read/normalization calls, keeps query and file_hash call counts unchanged, and preserves source drift and PIT behavior.
- Ruff, diff check, build, artifact inspection, and fresh Python 3.12 installed smoke pass.

## Repository context

Canonical requirements are docs/qlibx-prd.md. docs/qlibx-architecture.md is the current implementation baseline. The review input is the untracked docs/code-review/2026-08-07-2100-catalog-performance-profile-and-fix-plan.md and is not authority. Production responsibilities are src/qlibx/evidence/local.py, src/qlibx/project.py, and src/qlibx/data/store.py. Current highest implementation record is 045.

## Milestones

- [x] M0: Add exp_001 catalog performance harness and capture current-HEAD baseline.
- [x] M1: Bound recovery deserialization while preserving event-schema rejection; record 046.
- [x] M2: Memoize one backend per QlibxProject; record 047.
- [x] M3: Add bounded nested catalog sessions, typed conflict handling, project scopes and docs; record 048.
- [x] M4: Cache normalized observation frames while hashing every query; record 049.
- [x] M5: Re-measure, run full completion checks, conclude experiment, and archive this plan.

## Progress

- 2026-08-07: Re-read project manifest, policy, skills, current PRD/Architecture evidence, source and review. Confirmed the review is untracked and HEAD is ce15634.
- 2026-08-07: Established a green pre-change baseline: 231 passed in 469.68s using a task-scoped pytest basetemp.
- 2026-08-07: Completed M0. Added six reproducible tools under exp_001; Ruff and compile smoke passed. Full catalog profile passed 231 tests with 1,834 connections and 1,809 closes; full observation profile passed 231 tests with 206 queries, 206 query hashes, 322 source reads and 392 timestamp normalizations. The 800-publish buckets were 344.1ms at 100 and 443.3ms at 800 (1.29x).
- 2026-08-07: Completed M1. Recovery now schema-guards the full log but deserializes only unterminated attempts; the canonical unknown-schema test and new malformed/zero-row regressions passed. After buckets were 346.9ms at 100 and 403.3ms at 800 (1.16x); focused catalog tests were 12 passed and full suite was 233 passed in 428.02s. Record 046 contains exact evidence.
- 2026-08-07: Completed M2. QlibxProject lazily reuses one backend identity while direct/subclass construction remains unchanged. Focused project+catalog tests were 16 passed and full suite was 234 passed in 417.55s. Record 047 contains exact evidence.
- 2026-08-07: Completed M3. Bounded sessions hold one writer lock/connection, use operation cursors, allow same-thread nesting, and map competing access to CATALOG_SESSION_CONFLICT. Focused facade/recovery tests were 64 passed; the full profile passed 239 tests and reduced connections from 1,834 to 1,451 (20.9%). An 800-publish session measured 13.5ms in the first bucket and 19.5ms in the last (1.44x). Record 048 contains exact evidence.
- 2026-08-07: Completed M4. ObservationStore keeps contract- and field-isolated normalized frames but rechecks source existence and SHA-256 on each query. Focused PIT/integrity tests were 28 passed. The full profile passed 243 tests; reads fell from 322 to 254 and normalizations from 392 to 252 while queries increased from 206 to 215. Record 049 contains exact evidence.
- 2026-08-07: Completed M5. Plain full suite passed 243 tests in 343.70s; repository Ruff and diff checks passed; uv built wheel and sdist; the wheel installed into fresh CPython 3.12.13 and passed bounded catalog publish/load plus repeated observation query smoke. The first catalog smoke harness used the wrong load signature and then the wrong LoadedArtifact level; both harness defects were corrected before the passing run.

## Discoveries

- experiments/ and experiments/AGENTS.md were absent. The approved fallback uses the experiment-lifecycle skill's direct exp_NNN and experiment.yaml rules without inventing repository instructions.
- The review says five C0 scripts but contains six.
- The review's simple unterminated-event SQL would bypass CATALOG-EVENT-SCHEMA-001 for corrupted terminal JSON, so M1 retains a lightweight all-row schema-version guard.
- The chosen observation policy preserves per-query SHA-256; only frame read and normalization are cached.
- DuckDB probes failed twice inside the sandbox with WinError 5, including under workspace ASCII TEMP; the identical bounded commands passed outside the sandbox. The initial SQL probe also spent more than three minutes inserting 20k autocommit rows, so fixture setup now uses one transaction without changing measured queries.
- Current-machine I/O dominates the review machine: full profile close cost is 142.23s and event INSERT cost is 80.12s. The current 800-publish baseline already meets 1.5x due to this large fixed cost, so M1 must also compare recovery query/deserialization behavior.

## Decision log

- Use experiments/exp_001_catalog_performance, not the review's unnumbered directory.
- Keep PublicationEvent full deserialization for audit, but restrict recovery deserialization to unterminated attempts after a lightweight event-schema guard.
- Hold the existing writer lock for an outer catalog session; permit same-thread nesting by refcount and reject cross-thread reuse explicitly.
- Use registration_identity and field in the observation cache key; never skip file_hash.
- Do not stage, commit, push, or include the untracked review input.

## Validation

- Baseline: .venv/Scripts/python.exe -m pytest tests -q --basetemp .agent/test-runs/catalog-impl-baseline-1 -p no:cacheprovider -> 231 passed in 469.68s.
- Final: .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp .agent/test-runs/catalog-final-full-20260807-a -> 243 passed in 343.70s.
- Final repository Ruff -> passed with warnings only for pre-existing access-denied .agent/tmp directories; git diff --check -> passed.
- uv build -> qlibx-0.1.0 wheel and sdist; both archives inspected. Fresh CPython 3.12.13 wheel install passed catalog publish/load and repeated observation query smoke.

## Risks and recovery

- DuckDB writer sessions exclude other processes. Keep the scope bounded, map conflict explicitly, close in finally, and retain operation-per-connection behavior outside sessions.
- A cheap schema guard may still add catalog-size-dependent SQL work. If the 1.5x bucket criterion fails, stop without weakening the schema contract.
- Full-suite multiprocessing timing is load-sensitive. An isolated rerun diagnoses a timeout but is not a substitute for a final green full suite.

## Next action

No implementation action remains. Staging, commits, push, and inclusion of the untracked review input require separate user authorization.