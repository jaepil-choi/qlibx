# 190 — The layers are a table, and a test reads it

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M1;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:** the campaign's own diagnosis — an
AST pass over `src/vqapr` that folds every `vqapr.*` import into a package node and finds four
cycles.

## Why

`pyproject.toml` declines an import-linter and gives a reason:

> a misplaced type surfaces as a circular import, which Python reports without a tool.

`tests/boundaries/test_a_deferred_import_states_its_reason.py` already records that this premise is
false where it matters — a function-local import defers the cycle to the first call, so Python
stops reporting it — and caps the deferrals at twelve. What it does not do is say what the layers
*are*, so nothing fails when a package acquires a dependency on something above it. Four cycles
exist today and three of them are held open by exactly that mechanism:

| cycle | how it is held open |
|---|---|
| `account ↔ exchange` | not held open at all; both edges are module-level |
| `exchange ↔ orders` | `exchange/execution_table.py:534-535`, deferred |
| `authoring ↔ account` | `account/history.py:33`, `TYPE_CHECKING` |
| `extension ↔ testing` | module-level both ways; import order happens to work |

This is the same failure `docs/issues/archive/028` cost: `docs/design/agent-first-surface.md` named the
facade boundary and gave the command to measure it, a step took the count from 12 to 13, and the
1,400-test suite stayed green because the tripwire lived in a document nobody executes. The fix
then was `test_the_facade_is_not_reached_up_to.py`. This is that fix generalised from one boundary
to all of them.

**It is armed before the first code-moving step**, for the reason the deferred-import ceiling gives
about itself: every remaining milestone moves code between modules, and the cheapest wrong way to
fix a resulting circular import is a new violation. Without the ratchet, this campaign's own
execution is the most likely thing to add one.

## What

**`tests/boundaries/test_the_layers_hold.py`**, three assertions over one table.

`LAYERS` maps each package node to an altitude, and a module may import only a **strictly** lower
number. Strict, not lower-or-equal: equal layers would permit `a -> b` and `b -> a` between two
packages sharing a number, which is the thing being forbidden. Sibling packages that genuinely
depend on each other therefore carry different numbers rather than being called peers. Altitudes
are spaced by ten so a package can be inserted without renumbering, and so the campaign's
intermediate states — `orders/` before it folds into `exchange/`, `testing/` before it folds into
`extension/` — have a truthful number while they still exist.

`flow` is the one package split into sub-nodes (`flow.engine`, `flow.declaration`, `flow.strategy`,
`flow.datamodel`, `flow`), because its root holds two altitudes: the substrate its phases read and
the assembly that drives them. Every other package is one node.

The table is not a permission system. `pyproject.toml`'s second argument stands — a contract must
not drive type placement — so what the table records is the altitude the package already has, plus
the one rule that keeps it:

> **A value two packages exchange lives in `domain/`. A package holds behaviour.**

Every measured cycle breaks that rule the same way. `Fill` sits in `exchange/`, `OrderBatch` in
`orders/`, `AccountSnapshot` and `AccountHistory` in `account/` — each a value two packages pass to
each other, each forcing the package that owns it to be imported by a package below it.

**`OPEN` holds the eleven violating edges measured at `develop @ 7c804ddc`**, each naming the
milestone that closes it: three for M2 (the values move to `domain/`, `orders/` folds into
`exchange/`), one for M4 (`testing/conformance` folds into `extension/`), four for M5 (the project
layer; `RunDefinition` is a registered declaration and belongs with the others, and
`register_component`'s persisting half stops opening a `Workspace` transaction from inside
`extension/`), three for M6 (`loop`/`artifacts`/`run_state` move to `flow/engine/`).

`OPEN` may shrink and may not grow, and `test_the_open_set_is_not_slack` asserts equality rather
than containment — a closed edge leaves the table in the commit that closes it. An entry that no
longer describes reality is permission for the next accident to reoccupy the slot, which is exactly
what the facade count did.

`test_every_node_has_a_declared_layer` is the third assertion and the least obvious. Without it the
other two pass by ignorance: an unplaced package is not a violation, it is invisible.

**`tests/boundaries/test_domain_imports_only_itself.py` is deleted, absorbed.** `domain` is layer 0
and layer 0 may import nothing, which is that test generalised. The general form is also slightly
stronger: it walks `rglob` rather than a single `glob`, so a future `domain/` subpackage is covered.

## Trade-offs

**A table someone must maintain.** A new package fails `test_every_node_has_a_declared_layer` until
it is placed, which is one more step when adding one. That is the point — the alternative is the
package landing at whatever altitude its first import happens to imply, which is how the current
four cycles arrived.

**Package granularity, not module.** The test folds `vqapr.data.scan` and `vqapr.data.store` into
one node, so a cycle *within* `data/` is invisible to it. Python still reports those, because a
same-package cycle is not the kind anyone defers. Going finer would make the table a mirror of the
file tree rather than a statement about it.

**Eleven edges are declared legal today.** The file is red in substance and green in CI until M6.
That is deliberate: a test that fails from the start gets disabled, and one that ratchets gets
tightened.

## Validation

- `uv run ruff check src/` — clean. The new file also passes `ruff check` on its own path (the
  declared gate covers `src/` only; three pre-existing findings in other `tests/boundaries/`
  files are untouched).
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/boundaries/ -q` — 37 passed (was 38 with the absorbed file; the deleted
  test contributed one).
- `uv run pytest tests/ -q` — 1578 passed, 2 failed. Both failures are in
  `tests/agent/test_the_release_records_what_it_ships.py` and were confirmed pre-existing by
  running that file against a stashed working tree at `develop @ 7c804ddc`: 2 failed, 4 passed.
  They are the release-only `_shipped.json` check, which `.agent/project.yaml` describes as
  *"meant to fail"* between releases; that it fails under the default `test` command rather than
  only under `release_check` is a separate finding, not this campaign's.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 401 s, the same two and no others:
  the slow set adds no failure.
