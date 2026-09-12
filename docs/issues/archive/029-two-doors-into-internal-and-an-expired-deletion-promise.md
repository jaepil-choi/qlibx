# 029 — `_internal` has two doors, and the note promising to close one names a goal that has expired

**Status:** **CLOSED 2026-08-30** by `docs/implementations/098-one-door-into-internal.md`
(branch `fix/029-one-door-into-internal`), which finished what
`docs/implementations/097-the-facade-boundary-is-a-test.md` started on the `flow/judgments.py` row.
Both remaining bypasses now go through the adapters, `extension/loading.py` re-exports
`as_loaded_fingerprint` so `public.py` had a door to use, all eight docstrings cite
`docs/design/agent-first-surface.md` instead of a goal id, and that document gained the one-door
ruling the docstrings point at. `tests/boundaries/test_internal_has_one_door.py` makes it
executable - proven to fail on the exact bypass before being kept.

**Not closed here, deliberately:** the adapters still exist. Deleting them is `G008` and both of its
admission gates are still shut. What this bought is that the deletion is now four files removed with
every stale import breaking loudly, rather than a grep.

*Correction, 2026-08-30:* the first version of this status line named `flow/preflight.py`,
`flow/materialize.py` and `cli/register.py` as the sites left open. Those three are the **control
rows** of the table below - they already go through the adapters and are what "correct" looks like.
The bypasses are the bolded rows. Verified by grep against `develop` after 097 landed: the only
`from vqapr._internal` statements in `src/` outside `_internal/` itself are the four adapters at
`extension/*.py:11`, the frozen cluster inside `project.py`, and the two named above.

**Status when filed:** open. Found 2026-08-30 by the same owner-requested boundary audit that filed
`docs/issues/archive/028`, against `develop@ad4565f9`. Not a journey finding, and not a defect a user can
observe — it is a maintenance hazard that will surface as a mass edit the first time anyone acts on
the note the modules carry.
**Touches:** `src/vqapr/extension/component.py`, `.../fingerprint.py`, `.../loading.py`,
`.../registration.py`; the bypass sites `src/vqapr/cli/show.py:79-80,106`,
`src/vqapr/flow/judgments.py:26,51,145`, `src/vqapr/public.py:75`;
`src/vqapr/_internal/extensions/*.py` docstrings.

## Two spellings for the same import

Four modules under `extension/` carry no logic. Each is a forwarding adapter over its counterpart in
`_internal/extensions/`, and says so:

> *"Temporary forwarding adapter... It carries no logic of its own and will be deleted in G004; do
> not add deprecation warnings, fallbacks, or new behaviour here."* — `extension/loading.py:4-6`

The adapters are used, heavily — roughly 25 references in `src/` and 36 in `tests/`. That is fine;
that is what an adapter is for. The problem is that three call sites skip them and import
`_internal` directly, so the same four authorities are reached by two different names depending on
which file you are in. **The `door` column is the point of this table; the first three rows are the
control group, not the defect:**

| caller | door | reached as |
|---|---|---|
| `flow/preflight.py:27-28` | adapter ✔ | `vqapr.extension.loading`, `vqapr.extension.component` |
| `flow/materialize.py:30` | adapter ✔ | `vqapr.extension.loading` |
| `cli/register.py:59-60` | adapter ✔ | `vqapr.extension.component`, `vqapr.extension.registration` |
| `flow/judgments.py:26,51,145` | ~~bypass~~ → adapter ✔ | fixed by record 097 |
| **`cli/show.py:79,80,106`** | **bypass ✘** | `vqapr._internal.extensions.loading`, `.component` |
| **`public.py:75`** | **bypass ✘** | `vqapr._internal.extensions.loading` |

`flow/preflight.py` and `flow/judgments.py` are siblings in the same layer, written within days of
each other, calling the same functions by two different paths. Nothing in the tree says which is
correct, because both work.

## `public.py` uses both doors, three lines apart

```python
# `as_loaded_fingerprint` is imported from `_internal` directly rather than through
# `vqapr.extension.loading`, which is a transitional forwarding shim slated for deletion in G004
# and explicitly not to be grown.
from vqapr._internal.extensions.loading import as_loaded_fingerprint
from vqapr.extension.loading import load_constraint, load_exchange, load_strategy_model
```

— `public.py:72-76`. This is the only bypass in the tree that explains itself, and the reasoning is
sound as far as it goes: do not grow a module that is scheduled to die. But applied to one name and
not the three on the next line, it produces a file that imports from both sides of the same boundary,
and it is the reasoning a later reader will copy. `flow/judgments.py` and `cli/show.py` are that copy
already, without the comment.

## The label expired

All eight files — four adapters and four `_internal` homes — pin their deletion to `G004`.
`_internal/extensions/component.py:3-5` is representative:

> *"this is the physical home of the component-reference authority as of G002.
> `vqapr.extension.component` is a temporary forwarding adapter over this module until G004 hard
> deletion"*

`G004` no longer means that. In `gjc-handoff/session-03/goals.json`, `G004` is *"Implement Project
transactions, atomic publication, and wire the invocation adapter into the runtime"* — **complete**,
and unrelated. The goal that actually owned this deletion is session-01's `G004`, *"Dogfood and
hard-remove the old qlibx API"*, which was superseded by session-03's **`G008`** — *"Hard-remove the
old qlibx API, relocate retained authority, and seal the release pair"* — and `G008` is **blocked**
on two gates that `docs/design/agent-first-surface.md` records as still shut.

So eight files carry an instruction whose subject has been renumbered twice. A reader who looks up
`G004` finds a completed goal about something else and can reasonably conclude the deletion already
happened, or that the note is stale enough to ignore. Neither is true: the deletion is real, still
owed, and gated behind an owner decision nobody has been asked for.

## Why this is worth a file rather than a cleanup commit

The adapters are the right shape and should not be deleted here — that is `G008`, and this issue does
not touch its admission conditions. What is wrong is cheap and compounding: **an inconsistency that
makes the eventual deletion bigger every week.** Every new module that picks the `_internal` spelling
is one more site the `G008` cutover has to find by grep rather than by deleting four files and
letting imports break loudly. That is the difference between a deletion that the compiler proves
complete and one that is complete when somebody says it is.

`docs/issues/archive/028` is the same failure at the other end of the package, and both have the same root:
a boundary that is documented in prose and enforced by nothing.

## What closes it

1. **One door.** Pick a spelling and make all of `src/` use it. Through the adapters is the smaller
   edit and keeps the eventual `G008` deletion mechanical. Direct to `_internal` is defensible too,
   but then the adapters exist only for `tests/` and external callers, and that should be said out
   loud in their docstrings rather than left as a shrug.

   **After record 097 this is two sites, not three:** `cli/show.py:79,80,106` — three imports, all
   function-local inside `_model` (`show.py:70`), the third in its `ComponentKind.CONSTRAINT`
   branch — and `public.py:75`. `flow/judgments.py` already moved. Do not touch `flow/preflight.py`,
   `flow/materialize.py` or `cli/register.py`: they are already on the adapter side and are the
   shape the other two should match.
2. **Re-label or unlabel.** Replace `G004` in all eight docstrings with `G008`, or drop the goal
   reference entirely and cite `docs/design/agent-first-surface.md` instead — a document that will
   still be findable after the next renumbering. Prefer the document: goal ids in source comments
   have now expired twice.
3. **Keep `public.py:72-76`'s reasoning, generalise its conclusion.** Whichever door wins, that
   comment should describe the rule rather than one import's exception to it.

None of this is a behaviour change and none of it needs an implementation record beyond the one the
edit itself owes. What it buys is that the next module written under `flow/` has one obvious way to
load an exchange.

## Not in scope

`_internal` is not dead code, and this file should not be read as suggesting it. All nineteen modules
under it are reached from somewhere; the bridge cluster is exercised thoroughly by `tests/internal/`.
What `docs/design/agent-first-surface.md` established about that cluster — exercised only by the tests
written for it, no shipped command reaching it, frozen rather than deleted — was re-measured on
2026-08-30 and still holds exactly.
