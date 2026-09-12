# 112 — Registration without the CLI

**Closes:** Step 8 of the approved structural plan, and the structural cause behind
`docs/issues/archive/012`.
**Branch:** `step-08-registration-without-the-cli`.

## Why this change exists

`cli/register.py` was **1,093 lines**, and it was not a surface over registration logic — it *was*
the logic. It read the YAML, validated key sets, resolved relative paths, parsed agendas and
sessions, walked a `.py` with `ast` to find the sole authored subclass, and registered the result.

`docs/vqapr-architecture.md` §10.2 defines the CLI as a **product surface, not a layer**. A surface
that owns rules costs twice: the rules cannot be tested without driving argparse, and they cannot be
reached from any other entry point — so a second entry point grows its own copy and the two diverge.

`docs/issues/archive/012` is that divergence already paid for: `check` refused a spec that `run` completed,
because each verb decided for itself.

## What changed

`src/vqapr/declarations.py` holds the declaration-reading layer: the parsers, the key-set
validation, the `ast` walk, the section dispatcher, and `apply`. **`cli/register.py` is 1,093 → 95
lines** — argparse wiring, one call, and envelope rendering.

`register_authored` returns **data** rather than an envelope, and the CLI renders it. Building a
`success(...)` in the layer is what made the layer import the surface.

## The move exposed a real layering defect, and fixing it is most of this record

The first working version had `declarations.py` importing `vqapr.cli.envelope` and
`vqapr.cli.inputs`. That closed an **import cycle through every verb module** —
`vqapr.cli.__init__` imports `main`, which imports all seven verbs, one of which imports
`declarations`. The cycle was not incidental. It was the layering defect stating itself.

Three things moved as a result, each downward:

1. **`cli/inputs.py` → `vqapr/inputs.py`.** `InputError` and `read_yaml_mapping` are the refusal
   vocabulary for user-supplied input, and layers below the CLI already used them — **`flow/run_spec.py`
   imported `vqapr.cli.inputs` before this step.** A layer reaching into a surface for its own
   refusal type is the surface being in the wrong place, not the layer.
2. **`BoundedRefusal` → `vqapr/inputs.py`.** It is the base type for a refusal whose body is already
   bounded. `cli/envelope.py` still *renders* it; it no longer *owns* it.
3. **`register_dataset` and `register_execution_input` → `declarations.py`**, re-exported from
   `vqapr.public`. Unlike the other seven `register_*` helpers these are not one-line delegations —
   each validates before it writes — so the layer could not inline them without duplicating a rule.
   Importing them from the facade would have been the fan-in this campaign removes, so the
   dependency is inverted instead: the layer owns them, the surface names them.

An earlier attempt made `vqapr/cli/__init__.py` resolve `main` lazily to break the cycle. It was
reverted: `from vqapr.cli import main` then binds the *submodule* rather than the function, which
silently changes what `__main__.py` calls. Breaking a cycle by moving what is misplaced is a fix;
breaking it by making an import mean something else is a trap.

## The facade count moved, 12 → 11

`cli/register.py` no longer imports `vqapr.public` — `declarations.py` reaches the owning modules
directly. That is the trajectory record `105` recorded and deliberately did not assert.

Per that record's own rule, **the step that moves the number updates the assertion and the ruling's
list in one commit**: `tests/boundaries/test_the_facade_is_not_reached_up_to.py` now asserts 11 and
drops `cli/register.py` from its permitted list, and
`docs/design/agent-first-surface.md`'s "Verified value" and named list are updated with the reason.

## Validation

| check | result |
|---|---|
| `cli/register.py` | **1,093 → 95 lines** |
| `vqapr.public` importers | **12 → 11**, assertion and canonical ruling updated together |
| `tests/test_registration_without_the_cli.py` (new) | 3 passed |
| fast suite | **1475 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |
| baseline regeneration | deliberate; 4 codes relocated `cli/register.py` → `declarations.py`, none added or removed |

The new test is the audit's own criterion for this step: **the same registration performed with
`vqapr.cli` absent from `sys.modules`**, asserted afterwards so an accidental import is visible
rather than cached. A second test reads `declarations.py`'s AST and fails on any module-level import
of `vqapr.cli` or `vqapr.public`, because a runtime check only catches what the exercised path
touches. A third drives `cli.register.run` to prove the surface still registers the same document.
