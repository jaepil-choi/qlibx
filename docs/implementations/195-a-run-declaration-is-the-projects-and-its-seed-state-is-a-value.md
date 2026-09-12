# 195 — A run declaration is the project's, and the seed state it names is a value

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M5b;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:**
`tests/boundaries/test_the_layers_hold.py`, holding `("project", "flow.declaration")` open with
five modules of the project layer on the wrong side of it.

## Why

**A `RunDefinition` is a registered declaration, and it lived in the engine.** Since record `139` a
run is a name in the workspace: `runs:` in a declaration document, looked up by `vqapr run <id>`.
Five modules of the project layer read one — `store.py`, `state.py`, `document.py`,
`registration.py`, `references.py` — because the workspace stores registered runs beside registered
datasets, sources and components. All five reached up into `flow/declaration/run.py` to name the
type they persist.

`flow/declaration/` holds what preflight *makes* of a declaration — `frozen.py`, `preflight.py`,
`judgments.py`. The declaration itself is not that.

**The move was blocked by one import, and the import was the second defect.**
`flow/declaration/run.py:43` took `prepare_model_state` from `flow/run_state.py`, so relocating the
module would have swapped `project -> flow.declaration` for `project -> flow`: the same violation
one node over.

`prepare_model_state` is not engine machinery. It normalizes a memory, frames it with a payload into
one envelope, and hashes it — no clock, no account, no IO — and `StrategyConfig` calls it to derive
the ref of the memory a run *declares* it starts with. Three layers exchange it and none owns it,
which is the campaign's rule verbatim.

## What

**`domain/model_state.py`** — `PreparedModelState` and `prepare_model_state`, moved out of
`flow/run_state.py`. A comment there recorded that this was `flow/model_state.py` until one-shape
Step 6 folded it in; it comes back out, but into `domain/` rather than `flow/`, because the fold was
the right call for the wrong package. It sits directly on the two things it is made of:
`ModelStateRef` from `domain/identifiers.py` and `normalize_memory` from `domain/values.py`.

It is not folded into `domain/values.py`, though that file holds `ModelMemory` and `normalize_memory`
and would need no new import. `values.py` imports nothing from `vqapr` at all, and that is worth more
than one fewer file: it is the floor the rest of `domain/` stands on, and adding an edge to
`identifiers.py` would be the first crack in it.

**`flow/declaration/run.py` -> `project/run.py`**, with `tests/flow/declaration/test_run.py` ->
`tests/project/test_run.py`. 28 modules changed the path they import it from.

**`OPEN` loses two, not one.** `("project", "flow.declaration")` was the target;
`("flow.declaration", "flow")` closed with it, because `run.py` was the only module under
`flow/declaration/` that reached into `flow/run_state.py`. One of M6's three edges is already gone.

Three remain: `("extension", "project")` for M5c, and `flow.strategy`/`flow.datamodel` -> `flow`
for M6.

## Trade-offs

**`flow/declaration/` is now three modules that never declare anything.** The name means "the run
declaration and what preflight makes of it", and only the second half is left. Renaming it is
tempting and is deliberately not done here: `frozen.py`, `preflight.py` and `judgments.py` are the
subject of no other milestone, and a rename purely for a name is churn this campaign has not earned.
Worth revisiting at M8.

**`vqapr.flow.declaration.run` is a breaking path** for the eleven `src/` modules and seventeen
tests that named it. `vqapr.public` re-exports `RunDefinition`, `RunExecution`, `RunFill`,
`StrategyEntry`, `DataModelEntry` and `ConstraintSet` unchanged, so the documented surface did not
move and no showcase needed an edit.

**`domain/` is now twelve modules.** That is the fourth time this campaign has answered "where does
this go?" with `domain/`, and the answer is starting to look like a default. It is not: each move
was forced by a measured cycle or a measured layer violation, and `portfolio/intents.py` was
explicitly left alone at M2 for want of one.

## Validation

- `uv run ruff check src/` — clean.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed, **0 codes lost**.
- `uv run pytest tests/boundaries/ -q` — 37 passed, after tightening. Before tightening it failed as
  designed, naming both closed edges: *"[('flow.declaration', 'flow'), ('project',
  'flow.declaration')]"*.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures from record `190`.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 265 s: identical to the pre-campaign baseline.
