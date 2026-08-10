# Typed execution spine and preparation

## Why this change exists

Daily KRX and Academic execution used unrelated keyword-heavy matcher calls and each flow assembled
its executable inputs directly. That made an Exchange hard to replace at a public run boundary and
left constraint adjustment as a standalone workflow rather than part of actual order preparation.
Execution evidence also lacked the exact venue identity and preparation parent needed to explain a
committed result.

## User and system outcome

`QlibxProject.run_daily()`, `run_daily_registered_strategy()`, and `run_academic()` now accept a
keyword-only Exchange object for each invocation. Omitting it creates the spec-derived built-in
venue; supplying it makes that object's ID and full configuration fingerprint part of the run
identity and evidence. No mutable project Exchange state or compatibility matcher signature was
added.

Every execution event now follows the explicit spine:

`intent -> concrete ExecutionPreparation -> typed BaseExchange request -> actual result commit`

KRX preparation constructs weights, optionally adjusts and validates the MVP constraint policy,
sizes orders from the execution-time Account and quotes, and freezes one preparation bundle.
Academic preparation independently freezes its signed portfolio state and quotes without importing
KRX cash, lot, or long-only semantics.

## Responsibility and flow changes

- `BaseExchange[RequestT, ResultT]` owns only stable identity and the typed `match_batch(request)`
  lifecycle. `KrxExchange` and `AcademicExchange` remain separate Strategy implementations.
- `OperationOutcome[T]` now types successful results across these boundaries.
- `KrxBatchRequest` and `AcademicBatchRequest` are immutable request authorities. Exchanges do not
  mutate Account or Strategy memory.
- `ExecutionPreparation[IntentT, ContextT, RequestT, EvidenceT]` defines the common lifecycle shape;
  KRX and Academic concrete implementations own their incompatible economics.
- Daily KRX emits one `krx_execution_preparation:v1` artifact before matching. Academic emits one
  `academic_execution_preparation:v1` artifact.
- `execution_result:v2` and `academic_execution_result:v2` record Exchange ID, Exchange config
  fingerprint, and preparation artifact ID.
- Constraint validation uses finding-level `passed` and aggregate `compliant`. A residual advisory
  breach is evidence and does not block matching; missing benchmark data or calculation failure
  ends before Exchange invocation and Account mutation.
- Zero-dealt diagnostics preserve requested and dealt quantities and reasons but create neither a
  Fill nor an Account commit.

## Alternatives and trade-offs

- A single universal KRX/Academic request or result was rejected because physical cash/lot/cost
  matching and hypothetical signed fractional rebalance have different ledger meanings.
- A project-level `set_exchange()` was rejected because hidden mutable composition would make
  replay and resume identity ambiguous.
- Multiple construction/constraint/sizing stage artifacts were rejected. The single preparation
  bundle preserves the fixed sequence without inventing a generic stage registry.
- Exchange configuration fingerprints include registered KRX instruments as well as venue config.
  This makes an injected venue's executable listing part of resume identity, at the cost that the
  fingerprint changes whenever the listing is explicitly changed.
- Existing Daily and Academic recovery state machines remain separate. No common journal was
  introduced.

## Validation

- Focused Exchange, Daily, Academic, constraint, and sample regression suite passed after the
  execution-spine migration.
- New boundary tests prove that an injected KRX instance is called, its preparation artifact is the
  exact execution parent, and its identity is present in execution evidence.
- New constraint integration tests prove adjustment and validation happen inside KRX preparation,
  and a missing benchmark prevents both preparation publication and Exchange invocation.
- Academic facade tests prove execution evidence references an Academic preparation artifact.
- `uv run ruff check` passed for changed production and focused test files.
- `git diff --check` passed.
- The protected concurrent review file retained SHA-256
  `6823FC506F5FCE6E92710F2E323D7CA56903403E670EC12B6FF6F92D78A05B05`.

## Remaining limitations and follow-up

> **2026-08-10 correction.** This section was written at `3f0c076` and named two limitations that
> later commits in the same milestone removed. Both are implemented:
>
> - `StrategyView.latest_execution_result()` exists and raises
>   `STRATEGY_EXECUTION_SCHEDULE_INVARIANT` when more than one execution occurred between
>   decisions, so the Strategy does read the exact execution result.
> - Dataset history is no longer pandas-backed. Registration publishes a normalized Parquet query
>   snapshot and `ObservationStore` queries it through DuckDB, pushing the declared `rows`/`calendar`
>   lookback into the SQL predicate. `strategy_result:v3` carries both lineage changes.
>
> `AccessRecord` originally recorded `requested_instruments` and `per_instrument_actual_count`.
> Those were replaced by a single `instruments_below_window: int`. Per-instrument enumeration
> exceeded what PRD 7.6.1 asks for (a requested/actual count), grew with the cross-section for every
> access record inside every published `StrategyResult`, and cost one full-column comparison per
> instrument. See `docs/code-review/2026-08-10-1730-execution-spine-conformance-review.md` C1.

Market impact, real short, sessions lookback, automatic constraint monitoring, and a unified
recovery journal remain outside this implementation scope.

`analyze_signal` still publishes `hypothetical_long_short_return`, which PRD 4.2 and 4.6 now forbid.
That removal is tracked separately as `GAP-RETURN-AUTHORITY-001`.

## Architecture alignment follow-up

Moving the observation source from pandas to normalized Parquet + DuckDB crossed a boundary the
architecture alignment table had marked as a future target. The table row and section 7 were updated
to describe the new actual. The stated transition condition asked for a representative workload
benchmark; `tests/performance/lookback_gate.py` provides the gate, but its before/after numbers are
not yet recorded here and should be added when the gate is next run.