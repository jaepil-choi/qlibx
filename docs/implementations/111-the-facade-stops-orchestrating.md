# 111 — The facade stops orchestrating

**Closes:** Step 7 of the approved structural plan.
**Branch:** `step-07-the-facade-stops-orchestrating`.

## Why this change exists

`public.py` was **776 lines, of which 450 were function bodies**: `run` (122),
`_registered_roster` (75), `_freeze_record` (72), `_contract_report` (57), `roster_report` (38),
`_as_loaded_identity` (23), `_FrozenCatalog` (12), `preflight_run` (5). The package's documented
surface was also its orchestrator.

Two consequences, neither theoretical:

- **Fan-in.** Every module below it that needed one of those functions had to import the top-level
  facade to get it — the defect `docs/issues/archive/028` records, where `flow/judgments.py` reached up
  through `vqapr.public` because that is where `Workspace` was re-exported.
- **A private consumer.** `cli/run.py:804` imported `_registered_roster` — a **private name** — from
  the documented surface. A private name crossing a module boundary is the surface admitting it is
  not one.

Record `104` already ruled that this facade survives rather than being replaced by frozen
`project.py`. That ruling is what makes emptying it the right move instead of migrating away from
it.

## What moved, and where

| moved | to | why there |
|---|---|---|
| `run`, `preflight_run`, `_FrozenCatalog`, `_as_loaded_identity` | `flow/orchestration.py` | beside `flow/preflight.py`, which freezes what it consumes, and `flow/run.py`, which defines the `FrozenRun` it takes |
| `_freeze_record` → `freeze_record`, `_contract_report` → `contract_report` | `evidence/records.py` | they build a run's durable record from a result — evidence production, which is what `evidence/` holds |
| `_registered_roster` → `registered_roster`, `roster_report` | `flow/roster.py` | read at run start, on the run path |

**Three were renamed public on the way.** They were private because a facade should not have had
public functions doing this work; in their own layer they are ordinary module API. `registered_roster`
is the one that mattered — it gives `cli/run.py` a public name to import, closing the private-consumer
defect rather than relocating it.

`register_dataset` and `component_ref` stay: both are already thin delegations over
`Workspace.create(...)`.

## No caller changed a line

`vqapr.public` re-exports all six names, so every caller, every test and every emitted scaffold
kept working. The re-exports use the explicit `from x import y as y` form — that marks intentional
re-export, and it is also what stops `ruff --fix` deleting them as unused, which it did once during
this step before the form was corrected.

**`public.py`: 776 → 351 lines.** `__all__` is unchanged, which is the acceptance clause that
matters: an emitted scaffold's `from vqapr.public import ...` is the most-copied artifact in the
package.

## What the tests had to learn, and what that revealed

Four test failures, each a test reaching into the facade for something that had moved. All four are
the move working as intended rather than incidental churn:

- `tests/boundaries/test_public.py` monkeypatched `public.load_strategy_model`, `load_exchange`,
  `validate_execution_input`, `RunStateRepository`, `SimulationFlow` and `preflight_run`. Those are
  the names `run` calls, so they are patched on `flow.orchestration` now. That the patch target had
  to move is the proof the function did.
- `tests/cli/test_a_run_reports_the_tables_it_declared.py` reads module **source text** to pin that
  the counter is named `instants` rather than `formations`. It now reads `evidence/records.py`.
- `tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py` (record `103`) imported
  `_registered_roster`; it imports `registered_roster`, and its docstring records the rename so the
  `docs/issues/archive/042` history stays legible.

## Baseline regeneration

Deliberate, and checked before accepting: **one code added, one removed, identical code sets**,
differing only in file — `public.py` → `flow/roster.py`. A pure relocation, which is exactly what
record `105`'s `(code, file)` key exists to report.

## The new gate

`tests/boundaries/test_the_facade_does_not_orchestrate.py`. A shape check rather than a list of
banned names, because the failure mode is gradual — one defensible helper at a time:

- **No function in `public.py` may hold more than 6 statements.** The survivors are delegations;
  six leaves room for an argument check and a call, and no room for a run loop. This is the
  assertion that actually says "facade".
- A loose 420-line ceiling, so slow accumulation of anything is visible. Deliberately loose: the
  file is mostly imports and a 132-name `__all__`, both of which grow legitimately.
- The six relocated names are still exported, imported through the facade exactly as a user would.
- **No module in `src/` imports a private name from `vqapr.public`.** Written as an AST walk over
  every module rather than a substring check — the first version matched `cli/run.py`'s own local
  helper `_registered_roster_for_report` and failed on a false positive, which is the difference
  between checking a property and checking a spelling.

## Validation

| check | result |
|---|---|
| `public.py` | **776 → 351 lines**, `__all__` unchanged |
| callers changed | **none** — all six names re-exported |
| `tests/boundaries/` | 37 passed (was 36; +1 file, 4 tests, −3 retired with their subject) |
| fast suite | **1472 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |
| baseline regeneration | deliberate; 1 code relocated, none added or removed |

`-m ""` was run because this step moves run assembly and record emission — the two things
`.agent/project.yaml` names as requiring it.
