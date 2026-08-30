# 098 — One door into `_internal`, and a note that outlives the next renumbering

**Closes:** `docs/issues/029-two-doors-into-internal-and-an-expired-deletion-promise.md`, the two
bypass sites and the expired label that record 097 left open.
**Branch:** `fix/029-one-door-into-internal`.

## Why this change exists

Four modules under `extension/` are forwarding adapters over `_internal/extensions/`. Each says it
carries no logic and will be deleted. Three call sites read that and concluded the sensible thing —
do not add callers to a module that is going away — so they imported `_internal` directly. The
result was one authority reached by two names depending on which file you were reading.

**The conclusion is backwards, and that is the finding.** A deletion whose callers all name one path
is four files removed with every stale import breaking loudly at import time. A deletion reached by
two paths is found by grep, and it is complete when somebody says it is. The bypass does not protect
the cutover; it is the thing that makes the cutover manual.

`public.py:72-76` was the origin. It is the only bypass in the tree that explained itself, and its
reasoning was applied to one name (`as_loaded_fingerprint`) while the three names on the very next
line came through the adapter. `flow/judgments.py` and `cli/show.py` are that pattern copied without
the comment. Record 097 fixed the first; this fixes the rest and removes the reason to copy it again.

The second half is the label. All eight modules pinned their deletion to a goal id that has been
reassigned twice — in `gjc-handoff/session-03/goals.json` it now names a **completed** goal about
Project transactions, and the deletion actually belongs to `G008`, which is blocked. A reader who
looked it up found evidence the deletion had already happened. It had not.

## What changed

- **`cli/show.py:79,80,106`** — three function-local imports now come from `vqapr.extension.component`
  and `vqapr.extension.loading`. Same objects; the adapters forward rather than copy, which
  `tests/extension/test_agent_first_internal_routes.py` has pinned since the relocation.
- **`public.py:72-76`** — the one direct `_internal` import is gone, folded into the adapter import
  beside its three neighbours. The comment kept its reasoning and generalised its conclusion: it now
  states the rule and why the deletion schedule argues *for* the adapter rather than against it.
- **`extension/loading.py` re-exports `as_loaded_fingerprint`.** This is the enabling edit, and it is
  maintenance of the forwarding surface rather than growth of it — the adapters' prohibition is on
  logic, fallbacks and deprecation warnings, not on forwarding one more name that already exists
  behind them. Without it `public.py` had no adapter to reach for, which is exactly how the first
  bypass got written.
- **Eight docstrings** drop the goal id. They now cite `docs/design/agent-first-surface.md`, state
  the one-door rule in the same breath as the no-new-logic rule, and name the test that enforces it.
  Two ids were removed, not one: the `as of G002` provenance marker has the identical failure mode
  and is already ambiguous between two sessions' numbering.
- **`docs/design/agent-first-surface.md` gains "The second boundary: one door into
  `_internal/extensions`"** — the rule, why the door is the adapter, the verified permitted list, and
  an explicit statement that the deletion itself stays under the `G008` conditions in the next
  section. The docstrings cite a document, so the document has to carry the ruling.
- **`tests/boundaries/test_internal_has_one_door.py`** is new.

## The test, and what it deliberately does not watch

An AST walk over `src/` outside `_internal/` itself, collecting every real `vqapr._internal` import.
Permitted: the four adapters, plus `project.py`, whose `_internal` edges are inherited and frozen by
the same design document. It fails in both directions, like the facade tripwire it sits beside: an
added importer is named with the door to use instead, and a *removed* one fails too, because the list
is the record of what the boundary is.

**Function-local imports count.** All three bypasses were inside function bodies — `cli/show.py`'s
were nested inside `_model`, one of them inside a branch — so a check that read module headers would
have called the file clean while the defect sat in it.

A second test pins that the adapter forwards `as_loaded_fingerprint` **as the same object**, not
merely that the name resolves. Two implementations that agree today is not one authority.

A third asserts the eight docstrings carry no goal id and do name the design document. That is the
half of `docs/issues/029` a boundary count cannot see, and it is the half that expired.

`tests/` are out of scope by design. They may import the physical home directly, and
`tests/extension/test_agent_first_internal_routes.py` exists to do precisely that.

## What this does not do

The adapters are not deleted here, and the `G008` admission conditions are untouched — both gates in
`docs/design/agent-first-surface.md` are still shut. This change makes that deletion mechanical when
it is admitted: remove four files, and every remaining caller breaks at import.

No behaviour changed. No refusal, envelope, record field or CLI output moves.

## Validation

| check | result |
|---|---|
| `tests/boundaries/` | 32 passed |
| `tests/extension/`, `tests/cli/test_show.py`, `tests/flow/test_edit_loop.py` | 154 passed with the above |
| `tests/characterization/` after baseline regeneration | 76 passed |
| fast suite (`slow` deselected) | **1418 passed**, 14 deselected |
| `-m slow` | **14 of 14 passed** |
| `ruff check` on every touched file | no new findings; the 2 in `public.py` are pre-existing at `HEAD` and were reproduced against `git show HEAD:src/vqapr/public.py` |

**The new tripwire was proven to fail on the defect it exists for.** `cli/show.py`'s adapter import
was temporarily reverted to `vqapr._internal.extensions.component`; the test failed naming
`src/vqapr/cli/show.py` and telling the reader which door to use. Then restored. The docstring test
failed the same way during development, on the first draft of the notes — which still spelled the
expired id inside the sentence explaining that the id had expired.

Baseline regeneration was a pure line shift: 12 rows, same codes, same files, moved by the added
docstring lines in `_internal/extensions/loading.py`, `.../registration.py` and `public.py`. Verified
by diffing the baseline with `"line"` fields excluded — no other field changed.
