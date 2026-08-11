# 068 — Remove interrupted-run recovery

## Why

PRD §9.10 distinguishes chaining completed runs from resuming an interrupted run, and §17.2 moves
interrupted-run resume outside current scope. The implementation still exposed `resume=` on daily
and academic APIs, persisted per-event simulation recovery points, restored partial Account/Memory
authority, and documented `RESUME_BRANCH_REQUIRED` as current behavior. That surface contradicted
the canonical product boundary and coupled unrelated event processing to a large recovery protocol.

## Outcome

Daily and academic runs now execute from their explicit inputs and publish one final checkpoint.
There is no public `resume=` parameter, simulation recovery-point artifact, candidate replay, or
partial-run hydration path. A failed or interrupted run is rerun from the beginning. Final Account
checkpoints remain usable as explicit input to a new run, frozen child execution remains supported,
and catalog publication conflict/idempotency/recovery is unchanged.

## Responsibilities and flow

- `DailyExecutionFlow` owns only current event ordering, Account mutation, evidence publication and
  final checkpoint creation; the separate `flow/recovery.py` coordinator was removed.
- `QlibxProject.run_daily()`/registered daily paths and academic APIs no longer accept `resume`.
- Academic execution publishes one final `AcademicCheckpoint` v2 without prior-checkpoint linkage.
- `SimulationCheckpoint` remains a portable completed-run artifact. Its current v4 schema carries
  final Account and strategy state; v2/v3 readers remain only for analysis of stored completed
  artifacts, not runtime resume.
- Recovery scenario registries and tests were removed from current scope. Catalog recovery tests
  remain because storage publication recovery is a different responsibility.

## Alternatives and trade-offs

Leaving dormant recovery APIs in place was rejected because public presence is a support claim and
the old protocol depended on the removed Strategy-memory authority. Keeping only checkpoint readers
is intentional: historical analysis and explicit seeding of a new run do not imply continuation at
an internal event position.

The current runtime can repeat work after interruption and may re-publish idempotent artifacts. It
does not promise exactly-once state continuation across process failure. That capability requires a
new product decision covering durable authority, external coordination and reconciliation.

## Validation

- Contract/traceability focus including public daily/academic and catalog recovery: 71 passed in
  60.61s.
- Full acceptance: 31 passed in 130.22s.
- Source search confirmed simulation recovery symbols and `resume=` call sites were removed while
  catalog recovery remained.
- Architecture and current-support documents now mark interrupted-run resume as Future and retain
  final checkpoint semantics.

## Remaining limitations

Production OMS reconciliation, external durable state and interrupted-run event recovery remain
future capabilities under PRD §§14.3 and 17.2.
