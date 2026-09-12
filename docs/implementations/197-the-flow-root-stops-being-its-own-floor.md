# 197 — The `flow/` root stops being its own floor, and the graph is a DAG

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M6;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:**
`tests/boundaries/test_the_layers_hold.py`, holding the campaign's last two edges.

## Why

`flow/` held two altitudes in one directory. Its root had the assembly — `orchestration.py` builds
a run and drives it, `freeze.py` turns what it produced into a record — and its subpackages had the
phases: `declaration/` for what preflight makes of a run, `strategy/` and `datamodel/` for the two
loops.

But three modules sat in that root *beneath* the phases rather than above them, and the phases
imported them fifteen times:

- `flow/strategy/*` -> `flow.artifacts`, `flow.run_state`, `flow.loop`: twelve statements
- `flow/datamodel/*` -> the same: one
- (`flow/declaration/run.py` was a fourteenth until record `195` moved it out of `flow/` entirely)

So the root was simultaneously above its children and below them. Python never complained, because
`flow.artifacts` and `flow.strategy.callback` are different modules and the import order works. The
layer table is what made it a failure rather than an observation.

## What

**`flow/engine/`** — `loop.py`, `artifacts.py`, `run_state.py`, moved verbatim.

The name says what they are: the substrate the phases share. Nothing in it knows what a strategy is.
`loop.py` merges a static schedule with the due events a callback mints, `artifacts.py` declares the
immutable evidence a phase emits, and `run_state.py` holds what a callback accepted until the
Account publishes it. All three import only `domain/`, `account/` and the authoring contract — which
is what makes them a floor rather than a peer, and what let this move be three `git mv`s and a path
rewrite in 23 modules.

`flow/` is now layered in one direction:

```
flow/orchestration.py, freeze.py, roster.py     assembly
  -> flow/declaration/, strategy/, datamodel/   the phases
    -> flow/engine/                             the substrate
      -> account/, authoring/, domain/
```

`flow/engine/__init__.py` carries the argument and re-exports nothing, per record `192`'s
convention: a door is for a published import path or for a package deliberately hiding its layout,
and this is neither.

**`OPEN` is empty, and the dict stays.** It held eleven edges when record `190` armed this file, each
naming the milestone that would close it; records `191`-`197` closed all eleven. The mechanism is
kept rather than deleted with its last entry, because a future campaign that must open an edge for a
step needs somewhere to declare it — and the alternative, `assert not violations` with no table,
leaves deleting the assertion as the only way to express a bounded exception.

**The package import graph is a DAG.** Four measured cycles at `4fdd46fb`; zero now.

## Trade-offs

**`vqapr.flow.artifacts`, `vqapr.flow.run_state` and `vqapr.flow.loop` are breaking paths** for the
23 modules that named them. `vqapr.public` re-exports `SimulationFailure` and `callback_evidence`
unchanged, so the documented surface did not move and no showcase needed an edit.

**`flow/` root is three modules and `flow/engine/` is three.** A reader could reasonably ask why the
root is not itself a subpackage — `flow/assembly/` beside `flow/engine/` — leaving `flow/` as a bare
namespace. That would be symmetric and is not done: `flow.orchestration` is where `vqapr.public.run`
lives (record `111`), the path is named in the facade's own boundary test, and renaming it buys
symmetry rather than a property anything checks.

**A fourth module could have gone in.** `flow/roster.py` reads the project's registered instrument
roster at run start, which is a project-layer read wearing a flow path. It stays in the root because
it is imported by `orchestration.py` alone and violates no layer: moving it would be a judgment about
naming, and this milestone is about a measured edge.

## Validation

- `uv run ruff check src/` — clean.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed, **0 codes lost**.
  `artifacts.py` renders the `strategy.<stage>` family, which the inventory treats as a re-render;
  the baseline is unchanged across the move.
- `uv run pytest tests/boundaries/ -q` — 37 passed. Before tightening it failed as designed, naming
  both closed edges: *"[('flow.datamodel', 'flow'), ('flow.strategy', 'flow')]"*.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures from record `190`.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 295 s: identical to the pre-campaign baseline.
