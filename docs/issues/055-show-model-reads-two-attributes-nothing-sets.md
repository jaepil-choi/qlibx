# 055 -- `show model` reads two attributes nothing sets, so `reads` is always empty and `records` never lists a declared table

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: `show model` builds `reads` from `inputs()`, `records`/`forms` from `tables()` and `account_history()`, and `decides` lists distinct dataset ids.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-005**), against `vqapr-0.3.0` (built wheel,
`develop @ 4f616f5a`). Confirmed against source the same day.

**Touches:** `src/vqapr/cli/show.py:158-176` (`_model`); `src/vqapr/authoring.py::Model.inputs`
and `StrategyModel.tables`, the surface that actually holds the facts.

## What happens

`vqapr show model ou-thresh-ff6` on a strategy that declares eight fields across two aliases and
one `TableSpec` printed:

```
"reads": {}, "decides": ["ff6-resid-values" x7, "kr-daily"], "forms": [], "records": []
```

The skill says `show model` describes *"what a component declares it reads, decides, forms,
weights and records"*. `reads` is empty although eight fields are declared; `records` is empty
although `tables()` returns one spec and the run then wrote that table (`ou_summary`); `decides`
is the dataset id repeated once per field.

## Why

`show.py:158-160` reads `model._aliases`, `model._authored_tables` and `model._authored_history`
with `getattr(..., {})` defaults. **No code in the tree assigns any of the three** -- a grep for
`_aliases` and `_authored_tables` finds only `show.py`. They are relics of a shape the convergence
campaign removed (records `126`-`133`): the model now declares reads through `inputs()` and tables
through `tables()`, and both are ordinary methods on the loaded object. `decides` is built from
`model.requirements()`, which fans one `DatasetInput` out to one `DataRequirement` per field, hence
the seven copies.

## What would have told the user directly

`reads` as `{alias: {dataset_id, fields, lookback}}` from `model.inputs()`; `records` as the ids
from `model.tables()` plus `vqapr.account` when `account_history()` is declared; `decides` as the
distinct dataset ids.

## What to do

Build `_model`'s payload from `inputs()`, `tables()` and `account_history()`, and add the test the
missing setter proves is absent: `show model` on the scaffolded strategy must list its alias and
its table. `getattr` with a silent default is what let this ship; the payload should fail loudly
if the model has no `inputs`.
