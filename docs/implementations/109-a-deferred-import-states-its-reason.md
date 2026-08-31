# 109 — A deferred import states its reason

**Closes:** Step 5 of the approved structural plan.
**Branch:** `step-05-a-deferred-import-states-its-reason`.
**Test-only. No `src/` change.**

## Why this exists, and why it is armed before the moving steps

`pyproject.toml` gives the reason this package declines an import-linter:

> a misplaced type surfaces as a circular import, which Python reports without a tool.

**That premise is already false where it matters most.** A function-local import defers the cycle to
the first call, so Python stops reporting it — and there are **111** of them in `src/`. Two thirds
sit in `project.py` (23) and the six `_internal/*_bridge.py` modules (55), which is the audit's S1
duplication seen from another angle: two definitions of one concept, and a translation layer that
can only avoid a cycle by importing late.

The ceiling is not a claim that deferred imports are wrong. It is a **ratchet**, and its placement is
the point. Every step from Step 6 onward moves code between modules, and the cheapest wrong way to
fix a resulting circular import is a new function-local import. Without a cap, *this refactoring's
own execution* is the most likely thing to push the number up. So it is armed before the first
moving step rather than after.

## What it asserts

`tests/boundaries/test_a_deferred_import_states_its_reason.py`, four tests:

- **The ratchet.** Total function-local `vqapr` imports, excluding justified modules, must not
  exceed `CEILING = 104`. The failure message carries a per-file breakdown, so it names where the
  growth happened rather than only that it happened.
- **The ceiling is not slack.** The count must *equal* the ceiling, not merely be under it. A cap
  set comfortably above reality stops being a ratchet and becomes permission; when a step removes
  deferred imports it lowers the constant in the same commit.
- **A justification cites a test.** `JUSTIFIED` holds `run_bridge.py` alone, whose laziness *is* its
  contract — `tests/internal/test_run_bridge.py:165`
  (`test_importing_run_bridge_does_not_pull_flow_or_workspace`) fails if those imports are hoisted.
  An entry must cite the test that would fail, because an entry asserting intent is exactly what
  this file exists to replace.
- **The allowlist does not go stale.** A justified module that stops deferring is dead weight that
  would silently absorb an unrelated accident later, so its entry must be removed.

`104`, not `111`: the total less the seven in `run_bridge`. The no-slack test caught that
off-by-seven immediately when the constant was first written as the raw total — which is the test
doing precisely its job on its first run.

The walk inspects function bodies rather than module headers, which is the whole distinction: a
module-level import is visible to Python's own cycle detection and a function-local one is not.

## Proven to fail on the accident it exists for

A single lazy `from vqapr.workspace import Workspace` was added inside `cli/list_.py::_runs` — the
exact shape a moving step would produce when it hits a cycle. The test failed:

```
AssertionError: function-local `vqapr` imports rose to 105, above the ceiling of 104.
```

Then reverted, with `git diff --stat` confirming a clean restore.

## Validation

| check | result |
|---|---|
| `tests/boundaries/` | 40 passed (was 36; +4) |
| fast suite | **1483 passed**, 14 deselected |
| `uv run ruff check src/ tests/boundaries/` | All checks passed |
| `src/` changed | **nothing** — this step adds a test and no source |
