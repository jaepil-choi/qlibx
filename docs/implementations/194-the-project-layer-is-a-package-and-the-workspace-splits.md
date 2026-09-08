# 194 — The project layer is a package, and the constraint that kept `workspace.py` whole is retired

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M5a;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:** the campaign's Step 0 measurement,
which was run specifically to decide whether this milestone could happen at all.

## Why

**Record `117` said this module could not be split, and it was right at the time.**
`workspace.py` was 2,227 lines with a four-way split planned. Only the codec half was taken,
because an attempt that moved `Workspace` away from `_workspace_error` measured **0 refusal codes
added and 37 removed** — with a green suite and a clean lint. Four repairs were tried and none
restored them. `test_the_codec_moved_and_the_refusals_did_not.py` pinned that measurement so nobody
would "finish the job" and delete a third of the refusal inventory in silence.

**The cost was never the split. It was the resolver.**
`tests/characterization/refusal_codes.py` folds a `code` argument forwarded through a helper, and
its index was per-file: a helper in another module was opaque, so codes left the baseline whenever a
module was cut. Record `171` rebuilt `_SourceIndex` over every module under `src/vqapr` at once, and
its docstring says what the old one did in the past tense — *"A per-file index only ever resolved a
code forwarded through a helper defined in the same file, so splitting a module dropped codes from
the baseline."*

**So the campaign measured it before moving anything.** `_workspace_error` was moved to a probe
module with its twenty-six callers left behind, and the gate reported **gained 0, lost 0**, all 22
literal codes still resolved. The probe was reverted; this record is the real move, and the gate
reports the same after it.

Beside that, three flat modules at the top level — `workspace.py`, `workspace_document.py`,
`declarations.py`, 2,884 lines between them — were one subject with no package, and the layer table
could only place them by giving each its own invented altitude.

## What

**`project/` — what a project accumulates between commands, and how a document enters it.**

| module | lines | holds |
|---|---|---|
| `store.py` | 957 | `Workspace`, `Transaction` (was `workspace.py`, 1,278) |
| `document.py` | 447 | the workspace document's pydantic shapes (was `workspace_document.py`) |
| `registration.py` | 1,159 | declaration document -> registered declarations (was `declarations.py`) |
| `merge.py` | 229 | folding one declaration into a state |
| `references.py` | 118 | what still points at a declaration, and the refusal that names it |
| `refusals.py` | 53 | `_workspace_error` |
| `state.py` | 32 | `_State` |

**Seven `Workspace` methods were free functions wearing `self`.** An AST pass over the class found
that `_merge_dataset` (122 lines, the largest single thing the class held), `_merge_component`,
`_merge_declaration`, `_references_in`, `_config_lookup` and `_reference_error` never read a `self`
attribute — they take a `_State`, decide, and return. They are module functions in `merge.py` and
`references.py` now, typed `(_State, ...) -> ...`, which makes them testable with a constructed
state and unable to reach anything the caller did not hand them. Every call site was inside the
class, so the rewiring was `self._merge_dataset(...)` -> `merge_dataset(...)`.

`_merge_run` and `_require_run_references` stay on the class: they read `self._runs` and the other
registries to check what a run names, so they are about a workspace rather than about a state.

`_State` gets its own module because three others need it, and a `_State` in `store.py` would make
`merge.py` and `references.py` both import the `Workspace` module to name their own argument type.

**No `__init__` re-export.** The convention record `192` stated applies: a door is for a published
import path or for a package deliberately hiding its layout, and `vqapr.project` is neither. Callers
name the module — `from vqapr.project.store import Workspace`.

**`test_the_codec_moved_and_the_refusals_did_not.py` is rewritten, not deleted**, as
`test_the_document_holds_the_shape_and_not_the_refusal.py`. Deleting it would have left the next
reader with record `117`'s conclusion and no record of its expiry; keeping it as-was would have
pinned a constraint the tree no longer has. The assertion *"the error constructor still lives with
its callers"* is gone and the file says why, with the measurement. What it still guards is the
property the original split was **for** and which nothing retired: the document module raises no
refusal of its own, the project layer has exactly one refusal constructor, and the legacy document
shapes stay in one region a later step can discard.

**`OPEN` re-nodes.** `workspace`, `workspace_document` and `declarations` leave `LAYERS` and
`project` replaces them at 50. Four entries collapse to two, because the same two defects are now
spelled once each: `("project", "flow.declaration")` for M5b, `("extension", "project")` for M5c.

## Trade-offs

**`store.py` is still 957 lines and `Workspace` is still one class.** Splitting a class across
modules means mixins, which this tree does not use and which would trade one navigation problem for
a worse one. What left was what could leave without inventing a base class: 290 lines that were
never methods in the first place. Whether the remaining class wants decomposing is a separate
question from the layering this campaign is about, and it is not answered here.

**`registration.py` is untouched at 1,159 lines.** Splitting it is M5b's work, not this commit's;
mixing it in would have put a package move and a file split under one message.

**A test's identity changed.** `test_the_codec_moved_and_the_refusals_did_not.py` was a name people
could search for. The new name says what the file now asserts, and the docstring carries both the
old measurement and the reason it no longer binds.

## Validation

- `uv run ruff check src/` — clean.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed, **0 codes lost**.
  This is the milestone's whole risk: the module holding twenty-six refusals was cut in four, and
  the baseline is unchanged. Record `117`'s measurement is retired by measurement, not by argument.
- `uv run pytest tests/boundaries/ -q` — 37 passed, after re-noding `OPEN` and rewriting the codec
  test. Six failed before those two edits, each naming a path that had moved.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures from record `190`. Two other
  tests needed a path updated — `test_a_declaration_is_one_transaction.py` used the
  `from vqapr import workspace as ...` form no path rewrite catches, and
  `test_registration_without_the_cli.py` reads `src/vqapr/declarations.py` as a file.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 299 s: identical to the pre-campaign baseline.
