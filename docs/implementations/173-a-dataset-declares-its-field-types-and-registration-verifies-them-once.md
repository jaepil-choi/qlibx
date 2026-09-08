# 173 — A dataset declares its field types, and registration verifies them once

**Closes:** `docs/issues/088`. **Branch:** `feat/088-declared-field-types`, on top of record
`170` (`07c9353e`, `develop`). **Owner ruling, 2026-09-08:** the user prepares the parquet, so
the user declares what each field is; the framework compares the declaration with the file once,
at registration, and refuses a mismatch. `049`'s "an author never writes a type" and `079`'s
rejection of a declared schema are reversed to that extent (both files carry the note).

## Why

`vqapr show dataset sample-prices` printed `field_types: {close: DOUBLE}` beside
`close: "78600.0000"`. The parquet was `decimal128(18,4)`; `scan._normalize` folded every
`DECIMAL` into `ColumnType.DOUBLE`; the store handed the model whatever the file held; so a field
the registration called `DOUBLE` reached every model as `Decimal`. The scaffolds and the SKILL
compensated with `Decimal(str(v))` on every cell because a model could not know which of two
numeric types it would get -- the defect record `051` met from the other side, where the sample
panel's decimal column hid a float bug from 691 tests. The registration measured a class, could
not be contradicted, and was wrong about the one thing a reader needed.

## What changed

**Vocabulary** (`data/scan.py`). `ColumnType.DECIMAL` exists and `_normalize` no longer folds
it. `DECLARABLE_FIELD_TYPES` is the closed set a declaration may use: `TIMESTAMP_TZ, DATE,
INTEGER, DOUBLE, VARCHAR, BOOLEAN`. `TIMESTAMP_NAIVE`, `DECIMAL`, `OTHER` are measured only, and
each is refused by name. `ProjectionSchema.observed` carries duckdb's own type string per field so
a refusal can say `DECIMAL(18,4)` rather than a class. `column_type_of_arrow` is the same
vocabulary read from an arrow schema, for the one producer that writes parquet itself.

**Declaration** (`data/datasets.py`, `workspace_document.py`, `declarations.py`).
`DatasetRegistration.of` takes `field_types`, required; `parse_field_types` refuses a missing
or extra field and a non-declarable name, with the permitted list. `with_schema` is
`with_aggregation`: grouping is still duckdb's verdict, the types are the author's. The YAML
`DatasetDeclaration` requires `field_types:`; the `declaration.read.value_invalid` refusal
distinguishes a field_types fault from a grain fault. `DatasetCodec` is unchanged on disk --
`field_types` was already written as a measurement, so an entry from the old regime decodes as
declared (what duckdb measured is what the author would have written), and an entry without it
is quarantined like one without `grain`: `require_grain` became `require_declared`, refusing
either by name (`dataset.register.schema.undeclared`).

**Verification** (`check_schema`). After the projection binds, per field: `DECIMAL` is
`field_decimal` (fix: cast to DOUBLE while preparing); naive timestamp and non-scalar keep
`field_not_tz` / `field_not_portable`; any other disagreement between the declared type and the
measured class is `field_type_mismatch`, quoting both and naming both fixes -- the author wrote
both the declaration and the file, so which is wrong is theirs to decide. `check_values` reads
the declared `DOUBLE` fields for the finite check, as it read the measured ones.

**DataModel output** (`flow/datamodel.py`). The producer states `field_types` from the arrow
schema of the first non-empty session (`_declarable`), so registration's `DESCRIBE` agrees by
construction. A value field whose type no declaration may carry -- a `Decimal` above all -- is
refused at that first append as `datamodel.output.field_type`, before any further session runs.
`schema_mismatch` for a later session that does not fit is unchanged.

**The sample panel** (`tests/sample/build.py`) writes prices as float64. Adjustment still
multiplies in `Decimal` so the warehouse's digits multiply exactly; the write is the `DOUBLE` the
dataset declares. `journey.py` declares the five field types. The reversal template and the
scaffold keep `Decimal(str(v))` as the one deliberate crossing into the intent's arithmetic; the
comments now say that rather than "a value keeps its parquet column's type".

**Surface.** `vqapr new dataset` emits `field_types:` with the permitted list and the DECIMAL
rule. The SKILL says a value arrives as the declared type, that `compute()` must return a
declarable type, and casts a record table's `weight` to `DOUBLE` rather than `DECIMAL(38, 12)`
(a weight on the `1e-12` grid is twelve significant digits; float64 carries fifteen). PRD §4.1
lists the type declaration as the fifth thing a minimal registration requires.

## Decisions

- **`field_types` is a sibling map of `fields`**, not `fields: {name: {expr, type}}`. It was
  already the on-disk shape; the codec validator already pinned key equality.
- **DECIMAL is not declarable.** The data plane carries one numeric type per kind; exact
  arithmetic lives on the money side of the execution boundary (`execution_table.py` converts a
  price once, explicitly). Reversible by adding it to `DECLARABLE_FIELD_TYPES`.
- **DataModel `value_fields` stays a list of names.** The producer states types from what it
  wrote. Whether the author declares them is the same question asked of user code; left open in
  `088`.

## What else moved

- **`SingleNameCap`** required a `Decimal` benchmark weight and would have refused the only type
  a dataset can now deliver; it crosses once via `Decimal(str(weight))` like every other consumer.
- **Execution inputs still admit a DECIMAL price** (`execution_table.py` numeric set gains
  `DECIMAL`): a venue price never reaches a model, it is converted once at the boundary, so the
  money side keeps whichever exact type the venue table carries. Without this every execution
  fixture built from a bare duckdb literal (`DECIMAL(4,1)`) was refused as non-numeric.
- **Fixtures.** A bare `100.0` in duckdb SQL is `DECIMAL(4,1)`, so every `VALUES`-built parquet
  a registration exposes now casts `::DOUBLE`; `pa.decimal128` observation fixtures are
  float64; the committed `tests/fixtures/real/*.parquet` (DECIMAL(18,4) close, DECIMAL(18,8)
  benchmark weight) stay binary and are registered as `CAST(... AS DOUBLE)` declared `DOUBLE`.
  `tests/characterization/refusal_codes.baseline.json` gains the four codes, all runtime-observed.
  `tests/agent/test_sample_panel.py::test_prices_are_exact` became
  `test_prices_are_the_double_the_dataset_declares`.
- **Tests added.** `tests/data/test_datasets.py` (parse refusals, `field_decimal` quoting
  `DECIMAL(18,4)`, `field_type_mismatch`), `tests/qa/test_quarantine_repair.py` and
  `tests/test_workspace.py` (an entry without `field_types` is quarantined and repaired),
  `tests/cli/test_register.py` (a declaration without `field_types` is `key_missing`; `DECIMAL`
  is `value_invalid` at `.field_types`), `tests/flow/test_a_second_session_..._type_drift.py`
  (a `Decimal` value field is `datamodel.output.field_type` at the first session).

## Validation

Worktree `.claude/worktrees/field-types`, 2026-09-08, with the three warehouse CSVs the slow set
reads copied in as plain files (no junction):

```
uv run ruff check src/                       All checks passed
uv run vulture                               (no output)
uv run pytest tests/ -q                      1422 passed, 15 skipped, 24 deselected   134 s
uv run pytest tests/ -q -m ""                1461 passed, 4 skipped                   421 s
  (one failure in that run, tests/agent/test_sample_panel.py::test_prices_are_exact,
   was the reversed premise itself; rewritten, 9 passed)
uv run python showcases/show_003_real_data_long_short/run.py   report written
```

`ruff check tests/` reports 21 pre-existing findings (E501, B017) on lines this change did not
touch; `ruff format --check src/` was already dirty on develop (10 files) and is not a gate.

## Limitations

- `value_fields` on a DataModel still carries names only; see `088` for the open question.
- `field_type_mismatch` compares classes, so a DOUBLE declared for a FLOAT (float32) column
  passes: both are `float` in Python and the class is what a model sees.
