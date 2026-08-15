# 006 — Register execution inputs before simulation

## Why this change exists

An execution-enabled run needs an exact-time table containing venue tradability and at least one
execution price. VQAPR already had a partial `ExecutionTableSpec` and could derive session times,
but a user could not validate and persist that input through the documented public facade. Treating
the table as an observation dataset would be incorrect because execution uses
`trade_at == execution_time`, not a PIT window bounded by `available_at`.

## User and system outcome

A user can now prepare a separate execution parquet, bind its physical fields and selected price to
a `FillConvention`, validate the actual rows, and persist the complete declaration in the project
workspace before simulation. Invalid selected prices fail before workspace creation or mutation.
The same execution parquet may support multiple explicit price bindings without silently
substituting one field for another.

## Responsibilities and flow

1. `SourceSpec` identifies the prepared physical parquet.
2. `ExecutionTableSpec` binds `trade_at`, instrument, tradability, and semantic price names to
   physical fields. It remains separate from `DatasetRegistration` and has no `available_at`.
3. `FillConvention` owns the session offset, local execution wall time, timezone, and selected
   semantic execution price.
4. `ExecutionInputRegistration` gives that pair a stable workspace identity.
5. `validate_execution_input()` performs staged schema, identity, selected-price, and local-time
   checks through `data.scan`; the execution module does not import DuckDB.
6. `vqapr.public.register_execution_input()` validates before opening or creating the workspace.
7. `Workspace` atomically persists `execution_inputs` alongside shared physical sources and
   observation datasets. Existing two-section workspace YAML remains readable.
8. `execution_session_times()` continues to derive the deterministic current-session sequence from
   sorted distinct `trade_at` values without exposing rows to Models.

## Validation rules

- `trade_at` is a timezone-aware timestamp.
- instrument is string and `is_tradable` is boolean.
- every declared execution price field is numeric.
- `(trade_at, instrument)` is non-null and unique.
- the selected `trade_price` is finite and positive whenever `is_tradable=true`.
- every execution instant matches the declared local time and IANA timezone.
- empty execution inputs fail.
- an unselected valid price never substitutes for an invalid selected price.

## Alternatives and trade-offs

- Reusing `DatasetRegistration` was rejected because it would add `available_at`, logical lookback,
  and Model-readable semantics to an Exchange-only exact-time input.
- Storing only a price-field name was rejected because the source, schema binding, time convention,
  and selected price together form the reproducible execution assumption.
- Loading rows into Python was rejected for scalability. Schema, key, conditional-value, and
  distinct-time checks execute as bounded DuckDB scans behind `data.scan`.
- A CLI command is not added in this slice. The documented Python facade proves the contract first;
  CLI design can wrap it later without duplicating validation.
- Order planning, fills, Account mutation, valuation, and return calculation remain outside this
  slice. The showcase states this boundary explicitly.

## User-visible evidence

`showcases/show_001_execution_input_registration/` creates actual observation, execution, and
invalid-price parquet files. Its HTML report shows the rows, persisted workspace declarations,
three derived sessions, close/open field bindings, and the structured invalid-price failure with
`workspace_unchanged=true`.

Reproduce with:

```powershell
uv run python showcases/show_001_execution_input_registration/run.py
```

Inspect `outputs/report.html`, `outputs/trace.json`, and `outputs/workspace.yaml`.

## Exact validation

```text
uv run pytest -q
-> 104 passed in 2.03s

uv run ruff check src tests showcases/show_001_execution_input_registration
-> All checks passed!

uv run ruff format --check src tests showcases/show_001_execution_input_registration
-> 147 files already formatted

uv run python -c "import vqapr"
-> exit 0

uv build
-> built dist/vqapr-0.1.0.tar.gz and dist/vqapr-0.1.0-py3-none-any.whl

git diff --check
-> exit 0 (Git emitted only configured LF-to-CRLF working-copy warnings)

uv run python showcases/show_001_execution_input_registration/run.py
-> succeeded; a second clean generation was SHA-256 byte-identical for every output
```

The deterministic evidence includes three parquet files, the project and copied workspace YAML,
`trace.json`, and `report.html`. The execution parquet SHA-256 is
`310b70bcc4bf5d61e049bcc308901394e9caa176d23b2dac6654cd4e19a9b0a3`; the final HTML SHA-256 is
`7844053306d1dd58d3756a02255f37e2161b4adcdb8b1652650d96f8161e8402`.

## Remaining limitations and follow-up

- `SimulationFlow` does not yet consume a registered execution input directly from a frozen
  `RunDefinition`.
- `Exchange.snapshot()` and `Exchange.execute()` are not implemented.
- No `OrderBatch`, `FillBatch`, Account commit, valuation, or performance result exists yet.
- Full run identity and result lineage will freeze this workspace declaration in the later run
  definition slice.
