# 027 Durable daily simulation recovery

## Why

The existing checkpoint test restored Account and Strategy Memory only after a normally completed
phase. It did not close GAP-RECOVERY-001: a process could terminate after an Account Fill/Mark
commit, after a Memory commit, or after evidence publication but before the final checkpoint.
Because the current Account and Memory implementations are local runtime authorities, a final-only
checkpoint could not reproduce the exact committed result at those boundaries.

## Observable outcome

The default local daily flow now resumes six deliberate process-crash points to the same result as
an uninterrupted run. Account cash, positions, marks, cost basis, journal, version and feedback
cursor match; Strategy Memory value, version, cursor and commit identity match; and the complete
Strategy/Decision/Execution/Mark/Monitor/Memory evidence collection plus catalog artifact identities
match. A changed request/config identity fails with RESUME_BRANCH_REQUIRED before Account or
Memory mutation.

The acceptance calculation uses bounded unchanged observations from
data/DW/fng_stock_daily_prices.csv. Only process termination is injected; decision prices, fills,
costs, marks and feedback are not mocked.

## Responsibilities and flow

- SimulationRecoveryPoint is a strict versioned artifact containing the post-CAS Account
  checkpoint, Strategy Memory snapshots, event position, completed decisions, pending execution
  identities and any typed evidence that might not yet have been published.
- Before a state-changing callback mutates the live authorities, Flow clones Account and Memory,
  applies the exact event ID, expected version and Memory commit identity, and durably publishes the
  validated candidate. It then applies the same change to the live Account and Memory and rejects
  any divergence.
- Resume loads the highest recovery sequence, validates request, config, profile, logical dataset
  registration and Strategy identity, restores Account and Memory, republishes missing typed
  evidence idempotently and schedules only events after the stored timestamp and priority.
- Strategy Memory commit IDs make exact replay idempotent while conflicting content under the same
  commit identity fails.
- Simulation checkpoint artifact schema is version 2. The existing artifact loader rejects an
  unsupported schema version rather than silently treating it as a raw dictionary.
- tests/scenarios/recovery.yaml owns the crash matrix separately from the PRD and Architecture.

Account journal and Strategy Memory remain the runtime authorities. Recovery points are portable
durable serializations of those authorities, not a mutable recovery ledger or a second assessment
object.

## Alternatives and trade-offs

A separate recovery coordinator, mutable path-assessment model, distributed transaction, and new
Account database were rejected. They would add authorities or deployment responsibilities not
needed by the current local simulation. Publishing only after live mutation was also rejected
because a process death between mutation and publication would still lose the only recoverable
state. Publishing a clone-validated candidate first creates one explicit durable commit decision
while preserving the existing Account and Memory reducers.

Recovery evidence stores validated JSON inside a tagged publication record. Resume maps each
supported tag to its concrete Pydantic model before publication; unknown tags and invalid payloads
fail. The current tags are limited to execution, mark and Memory evidence.

On Windows, a native library can replace the requested os._exit code during hard termination.
Each fixture therefore writes a boundary-specific marker immediately before exit and requires both
that marker and a non-zero process result.

## Validation

- Recovery scenario and registry: 8 passed.
- Account, Architecture, document and scenario contracts: 18 passed.
- Existing Account, execution and reporting regression: 21 passed.
- Full pytest: 112 passed in 216.59 seconds.
- Ruff: all checks passed.
- Public import smoke for recovery contracts and DailyExecutionFlow: passed.
- Build: qlibx 0.1.0 sdist and wheel built successfully.
- Wheel inspection: 86 entries and qlibx/flow/recovery.py present.
- Git diff check: passed.

## Remaining limitations

This protocol is for the default single-host local daily simulation. It does not claim distributed
transaction semantics, external Account persistence, OMS/broker acknowledgement recovery, intraday
pending-order recovery, real-short borrowing, settlement, futures or perpetual lifecycle recovery.
Changed identity requires a new run or explicit parent-checkpoint branch; divergent state is never
merged automatically.