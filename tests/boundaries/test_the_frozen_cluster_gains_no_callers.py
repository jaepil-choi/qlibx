"""The freeze's "no new callers" half, as a test rather than as a paragraph.

`docs/design/agent-first-surface.md` freezes five things — `project.py`, `simulation.py`,
`materialization.py`, `venues.py` and `vqapr.open` — on three counts: **no new callers**, no growth,
no deletion. It then says, in a section titled "What the tripwire does not watch":

> **The tripwire counts importers of `vqapr.public`, which is not one of the five frozen
> modules.** [...] A reader who runs the only command given here, sees 12, and concludes the whole
> freeze is intact would be reading a number that never looked.

That is exactly what shipped: `test_the_facade_is_not_reached_up_to.py` watches the facade, and
**nothing watched the five**. The document records their state on 2026-08-28 and says the numbers
are written down "so a later reader can tell an inherited edge from a new one" — a comparison no
test performed.

This file performs it. It pins the inherited edges and fails on a new one, which is the prohibition
as written: adding is forbidden, and the existing edges are legal precisely because they are
inherited.

**Owner ruling, 2026-09-01: there is no such thing as a frozen module.** *"필요하면 고치는건데
merge 할 때 어떤 것이 correct 한지 검토해야지"* — if a module needs fixing it is fixed, and whether
the change is right is settled by reviewing the merge, not by a standing prohibition. The **no
growth / no deletion / no edit** half of the freeze is therefore retired, and an edit to one of
these four files needs no escalation. The read-path campaign's lane C hit this immediately:
`DatasetDeclaration.instrument_field` becoming `str | None` is forced by the ruling in
`docs/issues/049` and is not growth by any reading.

**This test survives the ruling because it never asserted that half.** It counts *edges into* the
four modules, which is a different claim: these modules are scheduled to die at `G008`, and a new
importer is new coupling to code on its way out. That stays worth knowing whether or not anyone may
edit them. What the ruling removes is the sentence this docstring used to end with — that nothing
else about these modules may change without returning to the owner.

**And it is worth recording why the ruling was reachable at all.** The escalation gate it retires
was not self-enforcing: this test watches callers, so lane C's edit passed green and the breach was
found by reading the diff, not by a gate. A prohibition that only a human can notice is one the
merge review has to carry anyway — which is the ruling.
"""

from __future__ import annotations

import ast
import pathlib

FROZEN_MODULES: frozenset[str] = frozenset(
    {
        "vqapr.project",
        "vqapr.simulation",
        "vqapr.materialization",
        "vqapr.venues",
    }
)

# The inherited edges, measured at develop@73e95e18 and matching the canonical document's own
# 2026-08-28 record. Each is legal because it predates the freeze; each is one a later reader must
# be able to tell apart from a new one.
PERMITTED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {
        # `vqapr.open()` itself -- the one importer the document names for project.py.
        ("src/vqapr/__init__.py", "vqapr.project"),
        # The venue bridge, which the document notes "is itself inside the frozen cluster".
        ("src/vqapr/_internal/venue_bridge.py", "vqapr.venues"),
        # simulation.py is imported only by project.py.
        ("src/vqapr/project.py", "vqapr.simulation"),
        # `simulation.py:30` reads `from vqapr import authoring, venues`. An INHERITED edge, and
        # one this gate could not see until record `115` taught it the `from vqapr import X` form:
        # `node.module` is `vqapr` there and the frozen name is an alias, so nothing matched.
        # Both ends are inside the frozen cluster, which is why it was never a new caller -- but
        # it was also not in the list this file claims is the record of them, and
        # `docs/design/agent-first-surface.md` still says venues.py is imported only by
        # `_internal/venue_bridge.py`. Found by an architecture review of VB002.
        ("src/vqapr/simulation.py", "vqapr.venues"),
    }
)


def _edges() -> set[tuple[str, str]]:
    """Every `src/` module that imports one of the frozen modules, by AST walk.

    An AST walk rather than a text search, for the reason the canonical document gives about its own
    tripwire: these names appear in docstrings, comments and refusal strings, and a string count
    moves when a sentence is edited. Function-local imports count -- `project.py` defers most of its
    own, and a deferred import is still a caller.
    """
    found: set[tuple[str, str]] = set()
    for path in pathlib.Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in FROZEN_MODULES:
                    found.add((path.as_posix(), module))
                elif module == "vqapr":
                    # `from vqapr import venues` names the PACKAGE, with the frozen module as the
                    # alias. Missed entirely until record `115`, which is how a live edge
                    # (`simulation.py` -> `venues`) sat unrecorded while this file claimed to be
                    # the record of every one. The sibling gate in
                    # `test_internal_holds_no_extension_authority.py` already resolved this form.
                    for alias in node.names:
                        candidate = f"vqapr.{alias.name}"
                        if candidate in FROZEN_MODULES:
                            found.add((path.as_posix(), candidate))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FROZEN_MODULES:
                        found.add((path.as_posix(), alias.name))
    return found


def test_no_module_gains_a_new_caller_of_the_frozen_cluster() -> None:
    """The prohibition is on ADDING, so an added edge fails and a removed one does not."""
    actual = _edges()

    added = sorted(actual - PERMITTED_EDGES)

    assert not added, (
        "these modules import a FROZEN module and are not permitted to:\n  "
        + "\n  ".join(f"{importer} -> {module}" for importer, module in added)
        + "\n\n`docs/design/agent-first-surface.md` freezes project.py, simulation.py, "
        "materialization.py, venues.py and vqapr.open: no new callers, no growth, no deletion. "
        "If a CLI verb needs a capability that lives there, reach it through `vqapr.public` or "
        "lift the capability out -- do not import the frozen module. Deleting the cluster instead "
        "is G008, whose two admission gates are both shut."
    )


def test_a_removed_edge_is_reported_rather_than_blocked() -> None:
    """Losing an inherited edge is progress, not a breach — but the list must not go stale.

    The freeze prohibits adding. A removal is the direction G008 eventually goes, so it cannot be a
    failure. What it must not be is silent: this reports it, so `PERMITTED_EDGES` is updated
    deliberately in the same commit rather than drifting into a record of a tree that no longer
    exists.
    """
    removed = sorted(PERMITTED_EDGES - _edges())

    if removed:
        print(
            "\ninherited frozen-cluster edges that no longer exist "
            f"({len(removed)}, not a failure):"
        )
        for importer, module in removed:
            print(f"  {importer} -> {module}")
        print("update PERMITTED_EDGES in the same commit that removed them.")

    # No assertion on `removed` itself: a removal is legitimate and this test exists to report
    # it, not to gate it. `assert isinstance(removed, list)` stood here and was vacuous --
    # `sorted()` always returns a list. What is worth asserting is that the comparison ran
    # against a real, non-empty record of inherited edges, so an emptied PERMITTED_EDGES
    # cannot make this pass by having nothing to compare.
    assert PERMITTED_EDGES, "the inherited-edge record must not be empty"


def test_materialization_still_has_no_importer_at_all() -> None:
    """The document singles this one out, so it gets its own assertion.

    > `materialization.py` — **no `import` statement anywhere in `src/`**; reachable only as a
    > lazily resolved capability name in `__init__.py`'s `_CAPABILITIES`.

    Folding it into the edge set above would let a first importer pass as "one new edge among
    several". It is a stronger property than the others and is asserted as one.
    """
    importers = sorted(
        importer for importer, module in _edges() if module == "vqapr.materialization"
    )

    assert not importers, (
        "vqapr.materialization gained an importer, and it had none: "
        f"{importers}. It is reachable only as a lazily resolved capability name in "
        "__init__.py's _CAPABILITIES, which is what keeps it unshipped."
    )
