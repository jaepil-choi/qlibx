# 056 -- `check` reports one missing dataset once per field the component reads from it

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: one `check.dataset.unregistered` per dataset, the fields it wanted as `examples`.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-006**), against `vqapr-0.3.0`. Confirmed
against source the same day.

**Touches:** `src/vqapr/flow/judgments.py:437-460` (the loop over `component.requirements()` in
the dataset judgments).

## What happens

`vqapr check ff6-ou-thresh` before the materialization that produces `ff6-resid-values` had
finished returned **eight** failures for one missing dataset: seven `check.dataset.unregistered`
entries with identical `requirement`, `observed`, `fix` and `source` -- one per field the strategy
reads from that dataset -- plus one `workspace.dataset.lookup.missing` for the same id.

The skill promises `check` reports *"every INDEPENDENT problem at once"*. These are one problem.

## Why

`requirements()` fans a `DatasetInput` out to one `DataRequirement` per field
(`authoring.py::requirements_for`), and the judgment loop emits a failure per requirement without
grouping by `dataset_id`. `check.field.absent` a few lines below has the same shape but is
naturally per field; the unregistered case is not.

## What to do

Group by `dataset_id` before emitting: one `check.dataset.unregistered` per dataset, `examples`
carrying the fields the component wanted from it. Keep `workspace.dataset.lookup.missing` if it
adds something the first does not; otherwise it is the eighth copy.
