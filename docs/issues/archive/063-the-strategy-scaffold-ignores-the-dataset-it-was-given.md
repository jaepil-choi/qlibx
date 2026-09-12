# 063 -- the strategy scaffold takes `--dataset` and `--field` and still names its alias `prices` and describes a momentum ranker

**Status:** **CLOSED 2026-09-04** on `fix/0.4.0-open-issues`, record `docs/implementations/149-the-open-issues-at-0.4.0.md`: the alias is the dataset id in the strategy and datamodel templates and the class docstring names the dataset and field and calls the example signal a placeholder.

**Status when filed:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-002**), against `vqapr-0.3.0`. Confirmed
against source the same day.

**Touches:** `src/vqapr/extension/scaffold.py:27` (docstring *"Ranks the cross-section and holds
the strongest names."*), `:33` and `:79` (`return {"prices": read}`), `:37`, `:106`, `:120`
(`"prices"` on every read); `src/vqapr/cli/new.py` (`new strategy --dataset --field --lookback`).

## What happens

`vqapr new strategy ou-thresh --dataset residuals --field resid --lookback 30` emitted a file
whose `inputs()` returns `{"prices": read}`, whose `decide()` calls `call.read("prices", "resid")`,
and whose class docstring describes a long-only momentum ranker. The dataset and field names went
into the template; the alias and the description did not.

Harmless once understood, but a first-time user reads `prices` as a required alias name for a
moment, and the docstring describes a strategy they did not ask for. The agent renamed the alias
by hand.

## What to do

Derive the alias from `--dataset` (`{"residuals": read}` and `call.read("residuals", "resid")`),
or keep a fixed alias and say in a template comment that the alias is the author's own name for
the read. Make the class docstring a placeholder that names the dataset and field rather than a
description of the example strategy. The DataModel and Constraint scaffolds should be checked for
the same pattern.
