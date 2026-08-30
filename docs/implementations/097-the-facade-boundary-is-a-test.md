# 097 — The facade boundary is a test, not a paragraph

**Closes:** `docs/issues/028-a-module-below-the-cli-reaches-up-through-the-facade.md`, and the
`flow/judgments.py` row of `docs/issues/029-two-doors-into-internal-and-an-expired-deletion-promise.md`.
**Branch:** `fix/023-narrow-the-provenance-promise` (the audit landed mid-branch; see below).

## Why this change exists

An owner-requested boundary audit of `src/`, run against `develop@ad4565f9` while this campaign was
still in flight, found a regression **introduced by this campaign's own first story**.

`docs/design/agent-first-surface.md` ("The ruling — 2026-08-28") defines one instrument for the
facade boundary: the count of modules under `src/` with a real `import` of `vqapr.public`, excluding
string literals, measured by an AST walk. It records a **verified value of 12** and names all twelve.

`fix/015a-extract-judgments` moved `_judgments` out of `cli/check.py` into `flow/judgments.py` and
carried its `from vqapr.public import Workspace` along unchanged. `vqapr.public` is the CLI's
supported implementation surface and sits **above** `flow/`, so the new module reached back up
through the layer it was created to sit beneath. The count went to **13**.

**The entire 1,400-test suite stayed green**, because the tripwire lived in a document nobody
executes. That is the actual finding: not the import, which is one line, but that the mechanism
meant to catch it was prose.

## What changed

- **`flow/judgments.py` imports `Workspace` from `vqapr.workspace`**, which is where it is defined
  and where `flow/preflight.py:32` already takes it from. Count back to 12.
- **`tests/boundaries/test_the_facade_is_not_reached_up_to.py`** makes the ruling executable. It
  carries the ruling's own list of twelve, walks the AST, and fails in both directions: a new
  importer names the offending file and says where to import from instead; a *removed* importer also
  fails, because the list is the record of what the boundary is and a stale record is the next
  reader's problem.
  - A separate count assertion, so a failure says whether the count or the membership is wrong.
  - `cli/new.py` and `extension/scaffold.py` are pinned as **not** importers while genuinely
    containing the string, which is the exclusion the AST walk exists for — the ruling devotes a
    paragraph to the string-count failure mode, and this keeps the measurement from regressing into
    one.
- **`flow/judgments.py` reaches `_internal` through the `extension/` adapters** (`load_exchange`,
  `load_strategy_model`, `load_data_model`, `ComponentKind`), matching `flow/preflight.py:27-28` and
  `flow/materialize.py:30`. Issue 029's point is that two names for one authority is how a later
  deletion of those adapters misses a caller; the module I created was one of the callers using the
  second door.

## Why this landed on the 023 branch

The audit files appeared in the working tree during `fix/023-narrow-the-provenance-promise` and were
swept into its commit by `git add -A`. Noticed on review of the commit stat, not by intent.

Splitting them out afterwards would mean rewriting a commit already merged to `develop`, which the
campaign's own rules forbid touching. The honest alternative is what was done: complete the fix on
this branch, record it here under its own number, and say plainly that one branch carries two
issues' worth of work. The campaign's one-issue-one-branch discipline held for all fifteen planned
branches; this is an unplanned sixteenth item that arrived mid-flight, and pretending otherwise
would be worse than recording it.

## Validation

| check | result |
|---|---|
| `tests/boundaries/` | 22 passed |
| `tests/cli/test_check.py`, `test_check_collects.py`, `test_run_makes_the_judgments_check_makes.py` | 26 passed |
| **full suite, all marks** | **1418 passed**, then 1405 fast after baseline regeneration |

**The new test was proven to fail on the regression it exists for.** The `vqapr.public` import was
temporarily reintroduced; both assertions failed, naming `src/vqapr/flow/judgments.py` and reporting
`13 == 12`. Then reverted. A boundary test that has never been seen to fail is a boundary test
nobody has checked.

Baseline regeneration was a pure line shift: same file, same codes, moved by the added import
comments.
