# 007 — Materialize DataModel results as registered datasets

## Why this change exists

VQAPR could validate and register prepared observation parquet, but a registered dataset could not
yet enter a bounded Model callback. Giving a DataModel a file path, DuckDB handle, workspace, or
unbounded table would bypass declared lookback, permit look-ahead, and lose the exact input lineage.
The missing operation was therefore not merely `compute()`: it was the complete path from a
declared requirement to a restricted window and from producer rows to a package-stamped,
registered derived dataset.

## User and system outcome

A user can now register a project-local DataModel, select explicit timezone-aware evaluation times
and instruments, and materialize its values into deterministic parquet. The result is registered in
the same workspace as ordinary observation data, so another DataModel can consume it through the
same `DataRequirement` and PIT path. Execution data, sessions, calendars, orders, and Account state
do not participate in this operation.

## Responsibilities and flow

1. `DataRequirement` declares a consumer, registered dataset, framework fields, and one past-only
   `RowsLookback` or `CalendarLookback`.
2. `flow.views` constructs a `ModelWindow`; only that bounded capability enters
   `DataModelContext`.
3. `DuckDbObservationStore` resolves framework fields through the workspace and pushes
   `available_at <= evaluation_time`, selected instruments, and the lookback into DuckDB.
4. `RowsLookback(N)` ranks non-null observations separately for each `(instrument × field)`.
   `CalendarLookback` computes an IANA-timezone local-date lower bound with month-end clamping.
5. Every query produces an `AccessRecord` with requested fields/instruments, actual row counts,
   lower bound, and maximum input `available_at`.
6. A project-local DataModel source and JSON config receive a SHA-256 fingerprint. Loading rejects
   unreadable source, construction/type/requirement errors, and drift from the registered bytes.
7. `materialize()` invokes the model only at caller-declared, strictly increasing, unique,
   timezone-aware evaluation times. The context contains no workspace, execution input, or Account.
8. The DataModel returns semantic rows without `available_at`. VQAPR validates portable finite
   scalars, exact declared fields, requested instruments, and per-evaluation uniqueness.
9. VQAPR stamps each invocation with
   `max(evaluation_time, max available_at of returned observation accesses)` and writes deterministic
   parquet plus JSON lineage.
10. The staged parquet passes the ordinary dataset schema/key validator before files are exposed.
    New-file hard links prevent overwrite races; workspace registration is last, and an operation
    failure removes only files created by that operation.

## Contract and failure behavior

- Models cannot request unregistered framework fields or read an undeclared requirement.
- Lookback is mandatory and has no future-facing form.
- Empty, naive, duplicate, or unsorted evaluation times fail at `materialize.input`.
- Producer-controlled `available_at`, unknown instruments, duplicate instrument rows, wrong fields,
  unsupported scalars, and empty total output fail before publication.
- A compute failure at any evaluation exposes no partial dataset and leaves workspace bytes
  unchanged.
- Existing logical or physical outputs are never overwritten.
- Component source drift fails at `component.load` before compute.
- Legacy workspace YAML without `execution_inputs` or `components` remains readable.

## Alternatives and trade-offs

- Passing a parquet path or Store handle into the Model was rejected because it creates an
  unrecorded look-ahead path. Only Flow owns the Store-backed view construction.
- Reusing execution sessions as DataModel evaluation times was rejected. DataModel materialization
  is an explicit value-computation operation, whereas stateful Strategy cadence belongs inside
  Strategy callbacks.
- A separate `ArtifactRequirement` was rejected because a derived result is an ordinary dataset;
  two requirement paths would allow PIT behavior to drift.
- Producer timestamps were rejected because the package, not user code, must prove when a derived
  row became available.
- A public `CoverageRequirement` was not invented in this slice. Architecture section 15-4 leaves
  its field-axis shape unresolved; exact requested/actual access evidence is recorded now, while
  economic sufficiency remains the Model's decision.
- A generic implementation of all extension kinds was not added. This slice implements only the
  DataModel registration/loading path that the user-visible operation needs.
- Full evidence-catalog integration, recorder tables, private payload checkpoints, CLI wrapping,
  and crash recovery of unregistered orphan files remain later work.

## User-visible evidence

`showcases/show_002_datamodel_materialization/` creates an actual `price_daily` parquet containing
deliberately future-dated `999` values, materializes two two-row reversal windows, registers the
result as `reversal_features`, and consumes that result through a second DataModel. The HTML shows
the exact old/new closes, package timestamps, access lineage, persisted workspace, and structured
timestamp-forgery rejection with `workspace_unchanged=true` and `output_absent=true`.

Reproduce with:

```powershell
uv run python showcases/show_002_datamodel_materialization/run.py
```

Inspect `outputs/report.html`, `outputs/trace.json`, the input parquet, and the derived parquet and
lineage files below `outputs/project/.vqapr/materialized/`.

## Exact validation

```text
uv run pytest -q
-> 122 passed in 3.33s

uv run ruff check src tests showcases/show_001_execution_input_registration \
  showcases/show_002_datamodel_materialization
-> All checks passed!

uv run ruff format --check src tests showcases/show_001_execution_input_registration \
  showcases/show_002_datamodel_materialization
-> 154 files already formatted

uv run python -c "import vqapr; import vqapr.public"
-> exit 0

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl

git diff --check
-> exit 0 (Git emitted only configured LF-to-CRLF working-copy warnings)

uv run python showcases/show_002_datamodel_materialization/run.py
-> succeeded; a second clean generation was byte-identical for HTML, trace, derived parquet,
   and lineage
```

Final showcase SHA-256 values:

- `report.html`: `55559b3235bcbc8d56de89cb8e31da90a02f2148c3ee98bae9b782bc132b87d6`
- `trace.json`: `eeb69ac8bd7689da6e6e2d794b71457344443d759f633785c15bedf85e93c8e6`
- `reversal_features.parquet`:
  `0173786338e162872957d0e9a1bd60c581b57f1bafe413e823cbd31eabd852ff`
- `reversal_features.lineage.json`:
  `d8abbaae282822b5398ec19fea2b4e61dbd1b8d0528974b4af209b0e2fac0e9c`

## Remaining limitations and follow-up

- A frozen run identity does not yet capture these component and dataset declarations.
- StrategyModel does not yet consume the registered observation and execution inputs through a
  complete event callback run.
- Exchange snapshot/execute, OrderBatch, FillBatch, Account commit, valuation, and performance are
  still absent.
- Full evidence-catalog publication and restart recovery for an interrupted materialization are not
  implemented.
