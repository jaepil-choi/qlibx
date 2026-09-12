# 196 — The half of registration that writes belongs to the workspace

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M5c;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:**
`tests/boundaries/test_the_layers_hold.py` — this edge was not in the campaign's original diagnosis
and was found by the layer table at M1.

## Why

`extension/registration.py` opened a `Workspace.transaction` from inside `extension/`, while
`project/registration.py` called back down into `extension/` for `prepare_component` and
`register_component`. A cycle, and the wrong way round: what a workspace holds is the project's to
decide, not the installer's.

The file had already drawn the seam that fixes it, in `prepare_component`'s own docstring:

> The half of registration that can refuse. Split from the write so a declaration document can prove
> every component it names before any of them is persisted (`Workspace.transaction`), and so a
> single `register_*` below is exactly this plus one write.

*This plus one write.* The refusing half needs `extension/` — fingerprint the source, build the
`ComponentRef`, prove it conforms. The write needs the workspace. They were in one file because they
were written together, and the layer table is what made that visible: nothing failed, nothing was
deferred, and `import vqapr.public` worked the whole time.

This is the edge worth noticing about the campaign's method. The other three cycles were in the
diagnosis before any code moved, found by reading the import graph. This one was found by a table
that had to be written down first — the M1 argument that a layer nobody asserts is a layer that
rots — and it is the only defect here that no amount of re-reading the graph had surfaced.

## What

**Five functions move down to `project/registration.py`:** `register_component` and the four
kind-fixed wrappers `register_data_model`, `register_strategy_model`, `register_constraint`,
`register_exchange`. 107 lines, verbatim, under a banner that says where they came from and why.

They land next to their caller. `register_authored` — the Python-API path for registering one
component without a declaration document — was already calling `register_component` from
`project/registration.py`, and its own comment referred to the transaction *"`register_component`
opens anyway"*. The call is now in one file.

**`extension/registration.py` keeps `prepare_component` and drops the `Workspace` import**, and its
docstring stops promising a write it no longer does: *"Validate, fingerprint, and persist
project-local extension references"* becomes *"Validate and fingerprint a project-local extension
reference; write nothing."*

**`vqapr.public` imports the four from `project/registration.py`.** Same names, same `__all__`, no
user-visible change. The comment above that import — the one-door rule from `docs/issues/archive/029` — is
kept and annotated rather than moved: the rule is that these are reached by one path, and they still
are.

**Two tests were importing `ComponentRef` from `extension/registration.py`**, which re-exported it
incidentally. They now take it from `extension/component.py`, where it is declared — the same rule
`test_the_facade_is_not_reached_up_to.py` states in its failure message.

**`OPEN` is down to two**, both M6: `flow.strategy -> flow` and `flow.datamodel -> flow`. Every
cycle the campaign measured is closed, and the project layer is a DAG.

## Trade-offs

**`project/registration.py` grows to 1,276 lines.** It was already the largest module in the layer
and this adds to it. The alternative was a sixth module in `project/` holding five functions whose
only caller is in this file, which trades a long file for a hop. Splitting `registration.py` is a
size question, and this campaign has been careful to keep those separate from layering ones — the
same call record `194` made about `store.py`.

**`extension/registration.py` is now 101 lines and its name overstates it.** It prepares; it does not
register. `prepare.py` would be the honest name, and renaming it is not done here for the reason
record `195` gave about `flow/declaration/`: a rename purely for a name is churn, and M8 is where
the campaign looks at what its own moves left misnamed.

## Validation

- `uv run ruff check src/` — clean.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed, **0 codes lost**.
- `uv run pytest tests/boundaries/ -q` — 37 passed, after tightening. Before tightening it failed as
  designed: *"these OPEN entries no longer violate anything: [('extension', 'project')]"*.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures from record `190`. Three test
  modules imported the moved names from their old path and were repointed.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 291 s: identical to the pre-campaign baseline.
