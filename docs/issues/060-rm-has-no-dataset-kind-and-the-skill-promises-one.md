# 060 -- `rm` has no `dataset` kind, and the skill tells the user to remove a dataset registration

**Status:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-011**), against `vqapr-0.3.0`. Confirmed
against source the same day. This is the half of the earlier real-world finding C4/E1 (README
section 1) that record `139` did not close: `rm` exists for eight kinds, and a dataset is not one
of them.

**Touches:** `src/vqapr/cli/rm.py:33-41` (`RECORD_KINDS`, `DECLARATION_KINDS`);
`src/vqapr/agent/skill/SKILL.md:157` (*"to replace an output, remove its dataset registration
first"*); `src/vqapr/workspace.py::Workspace.remove`.

## What happens

The skill's materialization section says a materialization writes no output when the dataset id
is taken, and to replace an output, remove its dataset registration first. `vqapr rm --help`
offers `run`, `strategy`, `component`, `agenda`, `strategy-config`, `valuation-config`,
`monitoring-policy`, `run-definition`. There is nothing to try.

Three throw-away datasets (`ff6-resid-smoke`, `ff6-resid-timing`, `ff6-resid-dev`, ~1.3 GB of
materialized parquet and lineage between them) stay registered in the testbed workspace. Had the
full materialization failed half-way, the user would have had to pick a new id for the retry,
and every downstream declaration that named the old one would have had to change with it.

## What to do

`vqapr rm dataset <id>`: refuse while a registered run definition or a run record reads it (the
same reference check `rm component` makes), otherwise drop the registration and, for a
materialized dataset, the parquet and lineage under `.vqapr/materialized/`. Until it exists, the
skill line at `:157` promises a verb the CLI refuses -- the shape of `030`, which was closed by
making the promise and the verb agree.
