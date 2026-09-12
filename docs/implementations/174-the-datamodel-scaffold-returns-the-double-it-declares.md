# 174 — The datamodel scaffold returns the DOUBLE it declares

**Closes:** a 0.7.0 release-gate finding. **Branch:** `develop`, on the stamped tree (`d71f8d70`),
before the `v0.7.0` tag. **Scope:** one line of `extension/scaffold.py`, one test.

## Why

Record `173` made a DataModel's output types declarable-only: a `Decimal` value field is refused
at the first session (`datamodel.output.field_type`, 422). The datamodel scaffold `vqapr new
datamodel` emits computed its trailing return in `Decimal` (the deliberate crossing from the
DOUBLE the window hands it) and returned that `Decimal` as the row's value. So the unedited
scaffold, with real instruments in place of the placeholders, was refused by the very rule
`173` added. The 0.7.0 scenario stepper's trace found it (scene ②, frame 8); the strategy
scaffold has an unedited-run test, the datamodel scaffold only had an unedited-register test,
which cannot see a first-session refusal.

## What changed

- `extension/scaffold.py`, the datamodel template's `return`: `float(value)`, with a comment
  saying why -- a dataset field is DOUBLE, never DECIMAL, and the first session's row types the
  output for every later one. The `Decimal` arithmetic above it stays: the intent's own numbers
  are exact; only the row that leaves the model is a DOUBLE.
- `tests/extension/test_scaffold_runs_unedited.py`: a third test registers the datamodel
  scaffold with two real sample instruments and runs it to a registered dataset.

## Observed, not fixed

When that refusal fired, `vqapr run` answered `mutation: false` while `vqapr list datamodels`
showed an unfinished record directory for the run. The refusal is right; the envelope's claim
that nothing was written is not. Issue candidate, left open here.

## Validation

- `uv run pytest tests/extension/test_scaffold_runs_unedited.py -m ""`: 3 passed (20.7 s).
- `uv run ruff check src/`: clean. The release gate (`test_all`) is rerun on the tree the
  `v0.7.0` tag is cut from, after the skill redesign lands.
