# 185 — The execution table is a dataset, and the run picks its price

**Date:** 2026-09-08. **Branch:** `redesign/component-eventloop` (campaign M4b; plan
`.agent/plans/active/component-eventloop-redesign.md`). **Review:**
`docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md` §3, §8-4.

## Why

The venue table was the one table the framework refused to call data. It had its own section
(`execution_inputs:`), its own registration door (`register_execution_input`), its own
workspace store, its own identifier, and -- the part that made it wrong rather than merely
separate -- **the fill convention was welded to it**: `trade_price` lived inside the
registration, so a table that carried both `open` and `close` had to be registered twice for a
run that fills at the open and a run that fills at the close to coexist. The owner's ruling
(2026-09-08): *the execution table is data, treated specially; which price a run fills at is
that run's own choice.* The role belongs to the table. The fill belongs to the run.

## What

- **`datasets.<id>.execution: {is_tradable: <field>}`** (`data/datasets.py`, `ExecutionRole`).
  A venue table is registered like every other dataset: `available_at` is the instant its row
  is a fact about (`trade_at`), `instrument_field` names the instrument, its numeric fields are
  the prices the venue published. The role is the one thing it declares beyond that, and it is
  declared, never derived: a table with a boolean column is not thereby a venue table. The
  dataset door judges it (`execution_role_failures`): the flag must be BOOLEAN, and at least one
  numeric field must exist for a run to bind. Grain is `instrument_instant`,
  required. A non-finite close is refused the way any dataset's non-finite value is
  (`dataset.value_not_finite`); `show_001` now shows exactly that.
- **`runs.<id>.execution: {dataset, fill: {selector, at, timezone, trade_price}}`**
  (`flow/run.py`, `RunExecution`, `RunFill`). The run names the dataset and declares its own
  fill: the venue-local wall time, the scheduling rule, and which of the dataset's numeric
  fields is the trade price. `fold`/`offset` are the DST proof a stored declaration may carry.
  `exchange` and `execution` are declared together or not at all; a datamodel run declares
  neither. The run's `spoken()` now says its fill in one sentence beside its callback sentence.
- **Preflight binds the two** (`flow/preflight.py`, `bound_execution_table`): the dataset's
  physical columns become the `ExecutionTableSpec`, the run's fill becomes the
  `FillConvention`, and the result is the `ExecutionTable(dataset_id, table, fill)` the engine
  already ran on. `execution.dataset_has_no_role` refuses a run that names a plain dataset;
  `execution.price_not_a_field` refuses a `trade_price` the dataset does not carry. The frozen
  identity hashes the dataset id and the fill, so an open-fill run and a close-fill run over one
  table are two runs.
- **`execution_inputs:` is retired.** `Workspace.open` refuses a document that still carries it,
  naming record 185 and where the fill went. `register_execution_input`,
  `ExecutionInputRegistration`, `workspace.execution()`, `workspace.execution_inputs`, the
  `execution-input` template of `vqapr new`, and the `execution_input.*` refusal family are
  gone; the table-level checks that survive (`validate_execution_table`, run at preflight and
  at the public `run` door) are the `execution_table.*` family. `SECTIONS` is
  `instruments, datasets, components, runs`.
- **Declarations judge the closed set early.** `runs.<id>.execution.fill.selector` gets the
  same treatment as `initial_account.mode`: a wrong value is `declaration.value_not_permitted`
  naming both members, not a one-line pydantic error inside `run_invalid`.
- `vqapr.public` exports `ExecutionRole`, `RunExecution`, `RunFill`. The sample declaration,
  the run and dataset templates, the skills, `list` and `show` speak the new shape.
- **Showcases** 001 and 003-008 register the venue table through `register_dataset` and
  declare `execution=RunExecution(...)` on their runs; 001's "invalid registration" scenario is
  the dataset door's refusal.
- Tests: every fixture that registered an execution input registers a venue dataset (through
  the public door where a parquet exists, `with_span` where a placeholder stands in) and
  declares `execution: {dataset, fill}` on the run. The refusal-code baseline was regenerated
  deliberately.

## Trade-offs

- **Every stored run and every declaration document changes shape.** Allowed (fast development
  stage); the refusal at `open` says what to do and there is no migration. The sample and the
  showcases are regenerated, not migrated.
- **A price is a field expression, like every dataset field.** The committed real fixtures
  carry DECIMAL closes and declare `CAST(close AS DOUBLE)`; the venue table declares its
  price the same way, and the snapshot query and the positive-price check read the
  expression. The tradable flag stays a bare column: the venue reads it by name.
- **The table's price checks still run at preflight, not at registration.** The dataset door
  knows the flag is boolean and that a numeric field exists; whether the *chosen* price is
  positive on every tradable row (`execution_table.price_invalid`) is a question about the
  run's binding, so it is asked when the run binds. A table can therefore register with a zero
  close and be refused later by a run that picks `close` -- the right place, since a run that
  picks `open` is fine.
- **`ExecutionTable` and `ExecutionTableSpec` survive as engine values**, built by preflight.
  They are no longer registered by anyone; M5/M6 decide whether they stay public.
- **The showcase directory `show_001_execution_input_registration` keeps its name.** Its README
  and title say what it now shows; renaming the directory would touch every reference for a
  name only.

## Validation

- `uv run pytest tests/ -q` (fast set): 1572 passed, 5 skipped.
- `uv run ruff check src/`: clean. `uv run pyright src`: 180 errors (183 before).
- `uv run --no-sync python showcases/show_001_execution_input_registration/run.py`: runs; the
  invalid venue table is refused with the workspace byte-identical.
- Showcases 003-008 need `data/DW`, absent in this worktree; they run at M7 with `test_all`.
