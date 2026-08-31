# 117 — The codec is its own file, and the refusals stayed put

**Closes:** Step 11 of the approved structural plan, **partially and deliberately**.
**Branch:** `step-11-the-codec-is-its-own-file`.

Step 11 asked for `workspace.py` (2,227 lines) to become `workspace/{registry,codec,integrity,migration}.py`
with no file over 800 lines and a pure-move diff. **The codec split landed. The rest did not, and this
record is mostly about why** — because the obvious next action is for someone to finish the job, and
finishing it silently deletes a third of the refusal-code inventory.

## What landed

`src/vqapr/workspace_codec.py`, 693 lines of moved bodies: `_encode`, `_decode` (429 lines), the
eight `_detach_*` helpers, `_encoded_dataset`, `_decode_cached`, and the `_encode_requirement` /
`_decode_requirement` pair. `workspace.py` 2,227 → 1,542.

This is the half the plan itself called load-bearing: the legacy document shapes now sit together, so
a later step that retires one discards a region instead of hunting a 2,227-line module for the three
places it was handled.

**The diff is a pure move.** Bodies are verbatim; the only additions are the module docstring and the
import list.

## What did not land, and the measurement that stopped it

**Two independent blockers, both measured rather than argued.**

### The refusal inventory does not survive splitting the class from its error constructor

`tests/characterization/refusal_codes.py` resolves a refusal code by folding f-strings through at
most one or two levels of **local, same-file** helper indirection. Every workspace refusal reaches
`Failure.bounded` through the module-level `_workspace_error`, and the stage constants it
interpolates have to be module-level literals in that same file.

`workspace.py` had already written this down, about the constants:

> A module-level literal is what lets the refusal-code inventory fold `f"{SPAN_STAGE}.absent"`
> statically; an alias to another module's constant is opaque to that pass and the code would drop
> out of the inventory silently.

The warning applies with equal force to the error constructor, and nothing in the plan accounted for
it. The resolver **unions all callers of a parameter**, so a single unresolvable caller collapses the
whole set.

Measured on the full four-way split: **0 codes added, 37 removed.** Every `workspace.dataset.*`,
`workspace.agenda.*`, `workspace.component.*`, `workspace.source.*` and `dataset.register.span.absent`
code — with a green suite and a clean lint. Four repairs were attempted and none restored them:
moving `_workspace_error` back beside its 31 callers, moving `_require_span` with it, moving all six
remaining stage constants into the file whose f-strings fold them, and relocating the `SPAN_STAGE`
drift assert with its constant.

That is the pre-mortem's scenario 2 exactly — green tree, moved metric, wrong number — so it was
reverted rather than shipped.

### The two acceptance clauses contradict each other

No file over 800 lines **and** a pure-move diff. The `Workspace` class alone is **1,307 lines of
method bodies**. With every module-level function moved out, the best achievable was `codec.py` 808,
`integrity.py` 171, and `registry.py` **1,403** — 603 over. Reaching 800 requires carving the class
itself, by mixins or by extracting methods into free functions, and neither is a pure move.

## What Step 11 would need, which is an owner decision

Either the refusal-code scanner learns cross-module resolution — a change to the verification
apparatus, not in this story or anywhere in the admitted scope — or the split keeps `Workspace` and
`_workspace_error` in one file and the 800-line clause is amended.

`tests/boundaries/test_the_codec_moved_and_the_refusals_did_not.py` is the guard rail on that
decision. It asserts the codec constructs no `Failure`, that `_workspace_error` still lives with more
than twenty callers, that the five stage constants are still module-level string literals, and that
the legacy shapes are still together in the codec. The first two fail immediately if someone
completes the four-way split without solving the inventory problem first.

## Validation

| check | result |
|---|---|
| `workspace.py` | 2,227 → **1,542 lines** |
| `workspace_codec.py` | **863 lines**, bodies verbatim |
| **refusal-code inventory** | **0 added, 0 removed** — baseline untouched, not regenerated |
| `tests/boundaries/` | 41 passed (was 37; +4) |
| fast suite | **1498 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |

The inventory line is the one that matters. The baseline file is **byte-identical** — this split
required no regeneration at all, which is the difference between it and the version that was
reverted.
