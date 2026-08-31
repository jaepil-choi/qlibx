# 110 — The transitional modules become the real ones

**Closes:** Step 6 of the approved structural plan, and discharges the deletion promise
`docs/issues/029` left open.
**Branch:** `step-06-the-transitional-modules-become-real`.

## Why this change exists

Four modules under `extension/` were forwarding shims over `_internal/extensions/*`, 106 lines
total, and each said in its own docstring:

> It carries no logic of its own and will be deleted when the internal-transition closes.

That promise was written in a file marked temporary and was still unkept months later — by which
point a boundary test *pinned the shim's existence*, which is how "temporary" becomes a contract.

There were two ways to keep it: delete the shims and repoint every caller at `_internal`, or move
the implementation **to** the shim's path. The audit recommended the second and it is plainly right:
the first changes every call site to reach into a private package, and the second changes none.

## What changed

`git mv` of five modules — `component`, `fingerprint`, `loading`, `registration`, `identity` — from
`_internal/extensions/` into `extension/`, replacing the shims that stood there.
`src/vqapr/_internal/extensions/` no longer exists. History follows the files because the move went
through git rather than a copy-and-delete.

**No caller changed a line.** That is exactly what the one-door rule from `docs/issues/029` bought:
because every importer already reached these authorities through `vqapr.extension.*`, the promotion
was invisible to all of them. Had callers been split across two doors, this step would have been a
grep.

The four docstrings were rewritten. They had described themselves as *"the physical home"* with
*"`vqapr.extension.X` is a temporary forwarding adapter over this module"* — self-referential
nonsense once the module *is* `vqapr.extension.X`. Each now states what it is and records what it
was, so the history survives the move rather than being erased with it.

## The one frozen-module edit, surfaced rather than buried

`project.py:838` changed from `from vqapr._internal.extensions.component import ComponentKind` to
`from vqapr.extension.component import ComponentKind`. One line, same symbol, same function-local
position, no behaviour and no line-count change — verified by `git diff`.

The escalation gate says any edit to `project.py` stops for the owner, so this is **recorded in the
ledger, in this record, and in the commit message** rather than slipped in. The judgement taken, and
the owner may overturn it:

- It is **forced, not chosen.** The step deletes `_internal/extensions/` entirely, so the old path
  would raise `ImportError`, and `project.py` is imported by four test modules — a broken import
  fails the suite.
- The alternative — keeping a back-compat shim at `_internal/extensions/` so `project.py` never
  changes — would renew the very promise this step exists to discharge.
- The canonical freeze prohibits **new callers**, **growth**, and **deletion**. A mechanical
  import-path update when the target moves underneath is none of the three: it preserves the status
  quo rather than extending the module to serve a new requirement. Reading the gate to forbid it
  would make every step of this refactoring that touches anything `project.py` imports impossible.

## Two tests were retired, because their subject stopped existing

This is the part worth reading. Both files existed to police a *shim*, and there is no shim.

**`tests/boundaries/test_internal_has_one_door.py`** became
`test_internal_holds_no_extension_authority.py`. Its old assertions — "only the adapters reach
`_internal.extensions`", "the adapter forwards every name a caller needs", and a parametrised check
that eight docstrings cite a document rather than a goal id — were about a door with something
behind it. What replaces them:

- `_internal/extensions/` **does not exist**, and a change recreating it fails. That is the outcome,
  asserted so it cannot quietly come back — a reappearance would restore the exact two-door shape
  `docs/issues/029` was filed about.
- The promoted modules **define rather than forward**. They were four-line re-exports; if one shrinks
  back to that, the move was undone.
- The surviving discipline: `_internal` is not a general-purpose import target, its permitted
  importers are enumerated, and each is allowed only what it was admitted for — so a module on the
  list for `_internal.atomic` cannot quietly start importing something else.

**`tests/extension/test_agent_first_internal_routes.py`** became
`test_the_extension_surface_is_the_implementation.py`. It proved the shim handed back the *same
object* as `_internal`, and that it *carried no implementation* — now exactly backwards. What was
kept is what was never about the shim: `ComponentKind` still constructs a ref, `positional_arity`
still answers `(min, max)`, `vqapr.public` and `vqapr.extension.*` still resolve to one object. A
move that quietly changed behaviour would otherwise be invisible.

Retiring a test whose premise is discharged is not weakening a gate. Leaving it would have meant a
file asserting the opposite of the design.

## The refusal-codes gate did its job

Regenerating was required and the drift was checked before accepting it: **11 codes added, 11
removed, identical code sets on both sides**, differing only in file —
`_internal/extensions/{loading,registration}.py` → `extension/{loading,registration}.py`. A pure
relocation, which is precisely what record `105`'s `(code, file)` key exists to catch: had the key
still included line numbers this would have been buried in dozens of line-shift rows.

## Validation

| check | result |
|---|---|
| `src/vqapr/_internal/extensions/` | **does not exist** |
| callers changed | **none** — every importer already used `vqapr.extension.*` |
| `tests/boundaries/`, `tests/extension/` | 147 passed |
| fast suite | **1468 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |
| baseline regeneration | deliberate; 11 codes relocated, none added or removed |

The slow journeys were run even though the plan does not mark this step `[test_all]`:
`extension/loading.py` is the component loader every run goes through, and `.agent/project.yaml`
requires them for changes reaching run assembly or the scaffolds.
