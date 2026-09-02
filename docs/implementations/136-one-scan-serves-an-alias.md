# 136 — one scan serves every field an alias declares

**Closes:** `docs/issues/046` (first half; the second closed in `120`). The last lane of
`docs/refactoring/2026-09-01-the-read-path-campaign.md`. **Step:** 4 of
`docs/refactoring/2026-09-02-the-convergence-campaign.md` (M4).
**Authority:** the read-path campaign's lane D contract; `docs/issues/049` (a requirement names
one field; expressions over one dataset fuse into one `SELECT`).

## Why this exists

A `DataRequirement` names one field, so an alias over three fields is three requirements.
`models/calls.py::declared_rows` read them one at a time — three `window.observations` calls,
three scans of the same window — and joined the batches in Python on `(available_at,
instrument)`. That is the per-declared-input floor `046` measured, and `049`'s own words say why
it had to go: one-field-per-requirement *"is only affordable because … expressions over the same
dataset fuse into one `SELECT`"*. The fusing was the precondition; it had not been built.

## What was true, and made it small

`scan.observation_rows` already took a `fields` **mapping**, and its rows-lookback SQL already
ranks **each field's own last N rows** (`count(expr) OVER … AS rank_i`, keep a row where any
field is within its window, null the others). So one statement over an alias's fields returns
exactly the rows the per-field reads returned once joined: one row per (instant, instrument) any
field admitted, each field null outside its own window. The change is a call shape, not a
semantics change, and a test says so row for row.

## What changed

- `DuckDbObservationStore.query_many(requirements)`: one dataset, one lookback, distinct fields,
  refused otherwise; `fields` built from all of them; one `AccessRecord` naming every field with
  per-field `actual_rows`. `query(requirement)` is the one-field spelling of it.
- `ModelWindow.declared(requirements)`: the same at the window — each requirement refused if
  undeclared, exactly as a single one is; one access recorded. `observations` delegates.
- `_DeclaredReads.read` (both Model roles and Constraint) reads
  `window.declared(requirements_for(alias))`. `declared_rows` and the join are deleted, with the
  module docstring that described them.

## Measured

`tests/data/test_one_scan_serves_an_alias.py`, counting the statement rather than timing it:

- three declared fields (one an expression, `close * 2`) → **one** `observation_rows` call, **one**
  access naming all three; each field keeps its own last-N window and the rows are the union
  joined on the instant;
- the fused rows equal the per-field batches folded the way the deleted join folded them;
- an alias spanning two lookbacks, or an empty one, is refused; an undeclared field in the alias
  is refused as a single undeclared requirement is.

On the `ff_factors` shape the acceptance names — three aliases over three datasets, 2+1+3
fields — a callback is **3 scans where it was 6**. The campaign's "3 → 1" was written before
`049` made a three-field input three requirements; per alias, it is *fields → 1*.

## The harness is gone

The read-path campaign, `047` and `049` point at `kwam-enhanced-index/vqapr-performance-testbed/`
for the 806.61 s baseline and its ladder. No `wide_experiment.py`, `pivot_experiment.py`,
`bench.py` or `probes.py` exists anywhere under `kwam-enhanced-index/`. Both campaign documents
now say so, and the convergence campaign's Step 5 baseline is to be measured on the tree at the
time Step 5 starts rather than compared to a number this tree cannot reproduce.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1274 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ c454ba9d` (record `135` merged), measured: **1270 passed / 14
deselected** fast; **14** slow. The four new tests are the difference.
