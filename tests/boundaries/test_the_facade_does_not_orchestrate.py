"""`vqapr.public` names things. It does not do them.

Record `111`. `public.py` was 776 lines, of which **450 were function bodies** — `run` (122),
`_registered_roster` (75), `_freeze_record` (72), `_contract_report` (57), `roster_report` (38),
`_as_loaded_identity` (23). The package's documented surface was also its orchestrator, and the
consequences were not theoretical:

* every module below it that needed one of those functions had to import the top-level facade to
  get it, which is the fan-in `docs/issues/028` records;
* `cli/run.py` imported `_registered_roster` — a **private** name — from the documented surface,
  which is the shape that tells you a module has outgrown its role.

The bodies moved to the layers that own them. `vqapr.public` re-exports every one, so no caller and
no emitted scaffold changed a line. This file stops the orchestration coming back.

It is a size and shape check rather than a list of banned names, because the failure mode is
gradual: one helper at a time, each defensible on its own.
"""

from __future__ import annotations

import ast
import pathlib

PUBLIC = pathlib.Path("src/vqapr/public.py")

MAX_LINES = 328
"""The exact current size. A ratchet, not a budget.

**This was 420 and that was wrong.** Step 7's acceptance said "under 250 lines", the file came out
at 351, and the ceiling meant to police that was set 69 lines ABOVE the actual value and 170 above
the target -- so the next step could have added 69 lines to the documented surface and stayed green.
A configured gate that is open is not a gate, which is the finding record `105` opened this campaign
with. Caught by an external review of Step 7 (`docs/refactoring/2026-08-31-post-step-07-review.md`,
R8) and corrected in record `113`.

**Why the 250 target was not reachable, measured rather than argued.** Of the 328 lines here,
115 are imports and 139 are `__all__` -- 254 lines of pure surface declaration for the 132 names
this module exists to export. The remaining ~74 are the module docstring, blank lines, and
eight thin `register_*` delegations. Reaching 250 would have required dropping public names, which
is a different decision from moving orchestration out, and one nobody took. Record `111` states
this as an amendment to the acceptance rather than letting this constant hide it.

Lower it whenever the real number drops; raise it only in a commit that adds a public name and says
so.
"""

MAX_BODY_STATEMENTS = 6
"""How many statements a function in the facade may hold.

The survivors are thin delegations -- `register_dataset` opens a workspace and calls it, and the
seven other `register_*` functions are one-liners. Six leaves room for an argument check and a
delegation. It does not leave room for a run loop.
"""


def _functions() -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(PUBLIC.read_text(encoding="utf-8"))
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def test_no_function_in_the_facade_holds_a_body_of_work() -> None:
    """The assertion that matters. A facade delegates; it does not compute."""
    heavy = [
        (node.name, len(node.body))
        for node in _functions()
        if len(node.body) > MAX_BODY_STATEMENTS
    ]

    assert not heavy, (
        "these functions in `vqapr.public` have grown bodies:\n  "
        + "\n  ".join(f"{name}: {count} statements" for name, count in heavy)
        + f"\n\nThe limit is {MAX_BODY_STATEMENTS}. `public.py` is the documented surface; work "
        "belongs in the layer that owns it and is re-exported here. Record 111 moved 450 lines "
        "out for this reason, and the fan-in it caused is docs/issues/028."
    )


def test_the_facade_stays_a_surface_rather_than_a_module() -> None:
    """A crude ceiling, so a slow accumulation of anything is visible."""
    total = len(PUBLIC.read_text(encoding="utf-8").splitlines())

    assert total <= MAX_LINES, (
        f"`public.py` is {total} lines, above the {MAX_LINES} ceiling. It was 776 before record 111. "
        "If the growth is a new public name, raise the ceiling in the same commit and say which "
        "name. If it is a function body, move it to the layer that owns it."
    )


def test_the_relocated_names_are_still_exported() -> None:
    """The move must be invisible to callers, which is the whole reason it was safe.

    Imported through the facade exactly as a user or an emitted scaffold would.
    """
    import vqapr.public as public

    for name in (
        "run",
        "preflight_run",
        "freeze_record",
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
