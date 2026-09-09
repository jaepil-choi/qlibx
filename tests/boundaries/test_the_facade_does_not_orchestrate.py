"""`vqapr.public` names things. It does not do them.

Record `111`. `public.py` was 776 lines, of which **450 were function bodies** — `run` (122),
`_registered_roster` (75), `_freeze_record` (72), `_contract_report` (57), `roster_report` (38),
`_as_loaded_identity` (23). The package's documented surface was also its orchestrator, and the
consequences were not theoretical:

* every module below it that needed one of those functions had to import the top-level facade to
  get it, which is the fan-in `docs/issues/archive/028` records;
* `cli/run.py` imported `_registered_roster` — a **private** name — from the documented surface,
  which is the shape that tells you a module has outgrown its role.

The bodies moved to the layers that own them. `vqapr.public` re-exports every one, so no caller and
no emitted scaffold changed a line. This file stops the orchestration coming back.

It is a shape check rather than a list of banned names, because the failure mode is gradual: one
helper at a time, each defensible on its own. It was a size check too until 2026-09-01; see the
note above `MAX_BODY_STATEMENTS` for why the size half was retired and what it never measured.
"""

from __future__ import annotations

import ast
import pathlib

PUBLIC = pathlib.Path("src/vqapr/public.py")

# A line-count ceiling on this file used to live here (`MAX_LINES`, last 328). The owner retired
# line-count caps as acceptance criteria on 2026-09-01; record `118` carries the ruling and the
# three measurements behind it. The short version is that the number never measured the thing it
# was named for. Of the 328 lines it last pinned, 254 were imports and `__all__` -- pure surface
# declaration for the 132 names this module exists to export -- so the cap was mostly counting how
# many things `vqapr.public` is a surface FOR, and got tighter every time the package exported
# something new. Step 7's acceptance ("under 250") was unreachable for that reason and had to be
# amended in record `111`; the ceiling policing it was then set 69 lines above the real value and
# had to be corrected in record `113`; and in record `117` the same style of cap (800 lines per
# workspace module) contradicted its own step's other clause and cost a Step-11 revert.
#
# What replaced it is the check below, which was always the one carrying the meaning: a facade
# delegates and does not compute. That is a shape, and shape is what "this file has outgrown its
# role" actually is. A file can double in `__all__` without breaking it and cannot smuggle a run
# loop past it.

MAX_BODY_STATEMENTS = 6
"""How many statements a function in the facade may hold.

The survivors are thin delegations -- `register_dataset` opens a workspace and calls it, and the
seven other `register_*` functions are one-liners. Six leaves room for an argument check and a
delegation. It does not leave room for a run loop.
"""


def _functions() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every function in the module, including methods.

    `ast.walk`, not `tree.body`. Reading only top-level definitions meant a class body was invisible
    to the statement cap -- and `_FrozenCatalog`, one of the things record `111` moved OUT, is a
    class. Re-adding it with a large method would have passed the gate that exists to stop exactly
    that. Found by an architecture review of VB002.
    """
    tree = ast.parse(PUBLIC.read_text(encoding="utf-8"))
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _statements(node: ast.AST) -> int:
    """Statements in a body, counted THROUGH compound statements rather than across the top.

    `len(node.body)` counts a `for` loop as one statement no matter what is inside it, so a run loop
    -- the thing `MAX_BODY_STATEMENTS`'s docstring says it leaves no room for -- scored 1. Counting
    recursively is what makes the number mean what the docstring claims.
    """
    return sum(
        1
        for child in ast.walk(node)
        if isinstance(child, ast.stmt) and child is not node
        and not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )


def test_no_function_in_the_facade_holds_a_body_of_work() -> None:
    """The assertion that matters. A facade delegates; it does not compute."""
    heavy = [
        (node.name, _statements(node))
        for node in _functions()
        if _statements(node) > MAX_BODY_STATEMENTS
    ]

    assert not heavy, (
        "these functions in `vqapr.public` have grown bodies:\n  "
        + "\n  ".join(f"{name}: {count} statements" for name, count in heavy)
        + f"\n\nThe limit is {MAX_BODY_STATEMENTS}. `public.py` is the documented surface; work "
        "belongs in the layer that owns it and is re-exported here. Record 111 moved 450 lines "
        "out for this reason, and the fan-in it caused is docs/issues/archive/028."
    )


def test_the_relocated_names_are_still_exported() -> None:
    """The move must be invisible to callers, which is the whole reason it was safe.

    Imported through the facade exactly as a user or an emitted scaffold would.
    """
    import vqapr.public as public

    for name in (
        "run",
        "preflight_run",
        "freeze_strategy_record",
        "contract_report",
        "registered_roster",
        "roster_report",
    ):
        assert hasattr(public, name), f"`vqapr.public.{name}` disappeared in a relocation"


def test_the_facade_no_longer_has_a_private_consumer() -> None:
    """`cli/run.py` imported `_registered_roster` from the documented surface.

    A private name crossing a module boundary is the surface admitting it is not one. The function
    is public now, in the layer that owns it, and the CLI reaches it there.
    """
    borrowed: list[tuple[str, str]] = []
    for path in pathlib.Path("src").rglob("*.py"):
        if path == PUBLIC:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "vqapr.public":
                borrowed.extend(
                    (path.as_posix(), alias.name)
                    for alias in node.names
                    if alias.name.startswith("_")
                )

    assert not borrowed, (
        "these modules import a PRIVATE name from the documented surface:\n  "
        + "\n  ".join(f"{where} -> {name}" for where, name in borrowed)
        + "\n\nA private name crossing a module boundary is the surface admitting it is not one. "
        "Give the function a public home in the layer that owns it."
    )

    private_exports = [
        node.name
        for node in _functions()
        if node.name.startswith("_") and not node.name.startswith("__")
    ]
    assert not private_exports, (
        "`vqapr.public` defines private functions again: "
        + ", ".join(private_exports)
        + ". A documented surface with private functions has work in it that belongs elsewhere."
    )
