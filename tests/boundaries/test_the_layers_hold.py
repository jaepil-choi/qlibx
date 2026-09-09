"""The package is a DAG, and this file is where that is written down.

`pyproject.toml` declines an import-linter and gives a reason:

> a misplaced type surfaces as a circular import, which Python reports without a tool.

`test_a_deferred_import_states_its_reason.py` already records that the premise is false where it
matters: a function-local import defers the cycle to the first call, so Python stops reporting it.
That file caps the deferrals. This file is the other half -- it says what may import what, so a
cycle has to be *declared* here before it can exist, rather than being discovered by an audit.

**Why a table and not a contract file.** `pyproject.toml`'s second argument stands: a contract must
not drive type placement. So the table below is not a permission system -- it is a written record of
the altitudes the package already has, and the one rule that keeps them:

> **A value two packages exchange lives in `domain/`. A package holds behaviour.**

Every cycle the layering campaign measured (2026-09-08, `docs/refactoring/`) broke that rule the
same way: `Fill` sat in `exchange/`, `OrderBatch` in `orders/`, `AccountSnapshot` in `account/`,
`AccountHistory` in `account/` -- each a value two packages pass to each other, each forcing the
package that owns it to be imported by a package below it.

**Strictly lower, not lower-or-equal.** A module may import only a *strictly* lower layer. Equal
layers would permit `a -> b` and `b -> a` between two packages that share a number, which is the
cycle this file exists to forbid. It is also why sibling packages that genuinely depend on each
other carry different numbers rather than being called peers.

**The gaps are deliberate.** Layers are spaced by ten so a package can be inserted between two
others without renumbering the tree, and so the campaign's intermediate states (`orders/` before it
folds into `exchange/`, `testing/` before it folds into `extension/`) have a truthful number while
they still exist.

**`OPEN` is a ratchet, not an exemption list.** It holds the violations measured before the first
code-moving step, each naming the milestone that closes it. It may shrink; it may not grow. A step
that closes an edge deletes its line in the same commit -- the same discipline
`test_a_deferred_import_states_its_reason.py` applies to `CEILING`, and for the same reason: this
refactoring is itself the most likely thing to add a violation.

This file absorbs `test_domain_imports_only_itself.py` (deleted): `domain` is layer 0, and layer 0
may import nothing, which is that test generalised to every package.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE_ROOT = pathlib.Path(__file__).parents[2] / "src" / "vqapr"

FLOW_NODES = ("strategy", "datamodel", "declaration", "engine")
"""`flow/` subpackages that carry their own altitude; everything else under `flow/` is `flow`."""

LAYERS: dict[str, int] = {
    # 0 -- values and mechanisms every layer shares and none owns. Imports nothing.
    "domain": 0,
    "_internal": 0,
    # 10 -- one subject each, reached by everything above and depending only on the vocabulary.
    "data": 10,
    "portfolio": 10,
    "transforms": 10,
    "account": 10,
    "record": 10,
    "analysis": 10,
    # 20 -- the extension contract: everything a Component sees, and nothing above it.
    "authoring": 20,
    # 30 -- the venue. Reads the execution table, executes orders, and subclasses `Component`,
    # which is why the contract must sit below it.
    "exchange": 30,
    # 40 -- what installs a Component, and what evaluates one. Both load user code, so both
    # sit above every contract that code is written against.
    "extension": 40,
    "constraints": 40,
    # 50 -- what a project accumulates between commands, and how a document enters it.
    "project": 50,
    # 60-70 -- running one. The substrate the phases share, the phases, then assembly.
    "flow.engine": 60,
    "flow.declaration": 63,
    "flow.strategy": 65,
    "flow.datamodel": 65,
    "flow": 70,
    # 80 -- reading a finished record. Computes nothing a run did not store.
    "report": 80,
    # 90+ -- the surfaces.
    "public": 90,
    "agent": 95,
    "cli": 100,
    "__init__": 110,
    "__main__": 110,
}
"""Package -> altitude. A module may import only a strictly lower number.

`flow` is split because its root holds two altitudes: the substrate its phases read
(`engine`) and the assembly that drives them. Every other package is one node.
"""

OPEN: dict[tuple[str, str], str] = {}
"""Declared-legal violations. **Empty, and that is the point.**

It held eleven edges when this file was armed at `develop @ 7c804ddc`, each naming the milestone
that would close it, and the layering campaign closed all eleven
(`docs/refactoring/2026-09-08-the-layering-campaign.md`, records `190`-`197`). The graph is a DAG.

It stays here rather than being deleted with the last entry. A campaign that needs to open an edge
for a step should say so in the table and close it in the commit that closes it, which is what this
dict is for; deleting it would leave the next such campaign with `assert not violations` and no way
to express a bounded exception except by deleting the assertion.

May shrink, may not grow. An entry needs the milestone that closes it, and
`test_the_open_set_is_not_slack` fails the moment one stops describing reality.
"""


def _node(module: str) -> str | None:
    """The layer node a dotted `vqapr` module belongs to, or `None` for the package root itself."""
    parts = module.split(".")
    if len(parts) < 2:
        return None
    if parts[1] == "flow" and len(parts) > 2 and parts[2] in FLOW_NODES:
        return f"flow.{parts[2]}"
    return parts[1]


def _node_of_path(path: pathlib.Path) -> str | None:
    relative = path.relative_to(PACKAGE_ROOT).with_suffix("").as_posix().replace("/", ".")
    if relative == "__init__":
        return "__init__"
    return _node("vqapr." + relative.removesuffix(".__init__"))


def _edges() -> dict[tuple[str, str], list[str]]:
    """Every cross-node `vqapr` import, as `(importer, imported) -> ["path:line", ...]`."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = _node_of_path(path)
        if source is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in ast.walk(tree):
            if isinstance(statement, ast.ImportFrom) and statement.module:
                imported = [statement.module]
            elif isinstance(statement, ast.Import):
                imported = [alias.name for alias in statement.names]
            else:
                continue
            for name in imported:
                if not name.startswith("vqapr"):
                    continue
                target = _node(name)
                if target is None or target == source:
                    continue
                site = f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{statement.lineno}"
                found.setdefault((source, target), []).append(site)
    return found


def _violations() -> dict[tuple[str, str], list[str]]:
    return {
        edge: sites
        for edge, sites in _edges().items()
        if LAYERS[edge[1]] >= LAYERS[edge[0]]
    }


def test_every_node_has_a_declared_layer() -> None:
    """A new package must be placed before it can be imported.

    Without this the other tests pass by ignorance: an unplaced package is not a violation, it is
    invisible, which is exactly how a layer boundary rots without anything failing.
    """
    seen = {node for path in PACKAGE_ROOT.rglob("*.py") if (node := _node_of_path(path))}
    for source, target in _edges():
        seen.update((source, target))

    unplaced = sorted(seen - LAYERS.keys())

    assert not unplaced, (
        f"these nodes have no layer: {unplaced}. Add each to LAYERS with the altitude it actually "
        "sits at, and say in a comment what the package is for -- the table is the architecture."
    )


def test_no_module_imports_its_own_layer_or_above() -> None:
    """The DAG, asserted. `OPEN` may shrink; anything not in it is a new violation."""
    new = {edge: sites for edge, sites in _violations().items() if edge not in OPEN}

    breakdown = "\n  ".join(
        f"{source} ({LAYERS[source]}) -> {target} ({LAYERS[target]}): {', '.join(sites)}"
        for (source, target), sites in sorted(new.items())
    )
    assert not new, (
        "these imports reach a layer at or above their own:\n  "
        + breakdown
        + "\n\nA package that needs something from above is usually holding a value that belongs "
        "in `domain/`: move the value down rather than the dependency up. Deferring the import "
        "into a function hides the cycle from Python and is caught by "
        "`test_a_deferred_import_states_its_reason.py` instead."
    )


def test_the_open_set_is_not_slack() -> None:
    """A closed edge leaves `OPEN` in the commit that closes it.

    An entry that no longer describes reality is permission for the next accident to reoccupy it,
    which is what happened to the facade count in `docs/issues/archive/028`.
    """
    stale = sorted(edge for edge in OPEN if edge not in _violations())

    assert not stale, (
        f"these OPEN entries no longer violate anything: {stale}. Delete each line in the commit "
        "that closed it, so the ratchet tightens instead of leaving room."
    )
