"""`_internal` has no extension authorities left, and the two shared primitives are named.

**This file's original subject no longer exists, and that is the outcome rather than a loss.** It
was written for `docs/issues/029`: four modules under `extension/` were forwarding shims over
`_internal/extensions/*`, and the rule was that every caller reach the authorities through the one
door, so the shims' eventual deletion would be four files removed with every stale import breaking
loudly rather than a grep.

Record `110` discharged that promise the other way round. Instead of deleting the shims and
repointing callers at `_internal`, the implementations moved **to** the shim paths. No caller changed
a line — that is what the one-door rule bought — and `src/vqapr/_internal/extensions/` stopped
existing. A door with nothing behind it is not a door.

What survives is the discipline the rule was an instance of: `_internal` is not a general-purpose
import target, and the modules that may be reached from outside it are enumerated rather than
assumed.
"""

from __future__ import annotations

import ast
import pathlib

INTERNAL_ROOT = "src/vqapr/_internal/"

PERMITTED: frozenset[str] = frozenset(
    {
        # Reaches `_internal.atomic` for the one durable write (record `107`).
        "src/vqapr/flow/record.py",
        # Reaches `_internal.filelock` and `_internal.atomic` (records `106`, `107`).
        "src/vqapr/workspace.py",
    }
)

SHARED_PRIMITIVES: frozenset[str] = frozenset(
    {
        "vqapr._internal.filelock",
        "vqapr._internal.atomic",
    }
)
"""`_internal` modules any layer may import directly.

Not extension authorities and not scheduled for deletion: these are what the refactoring is
consolidating INTO — one exclusive mutex (record `106`) and one durable write (record `107`), each
replacing several copies that had drifted apart. Enumerated rather than a wildcard, so adding a
third is a decision somebody takes on purpose.
"""


def _internal_imports() -> set[tuple[str, str]]:
    """Every `(importer, module)` edge from outside `_internal/` into it.

    An AST walk because the string `vqapr._internal` appears in docstrings and refusal text, and a
    text count would move when a sentence is edited. Function-local imports count -- `cli/show.py`
    once reached `_internal` from inside a function body, and a check reading only module headers
    would have called that file clean.
    """
    found: set[tuple[str, str]] = set()
    for path in pathlib.Path("src").rglob("*.py"):
        posix = path.as_posix()
        if posix.startswith(INTERNAL_ROOT):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "vqapr._internal"
            ):
                module = node.module or ""
                if module == "vqapr._internal":
                    # `from vqapr._internal import atomic, filelock` names the package and the
                    # submodule is the alias. Resolving it is what lets a shared primitive be told
                    # apart from anything else, since both spell their package the same way.
                    for alias in node.names:
                        found.add((posix, f"{module}.{alias.name}"))
                else:
                    found.add((posix, module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("vqapr._internal"):
                        found.add((posix, alias.name))
    return found


def test_the_extension_authorities_no_longer_live_under_internal() -> None:
    """The outcome of record `110`, asserted so it cannot quietly come back.

    A future change that recreates `_internal/extensions/` would restore the exact shape
    `docs/issues/029` was filed about: one authority reachable by two names, and a deletion that
    has to be found by grep.
    """
    # Modules, not the directory. `.exists()` failed on a tree that had merely kept the stale
    # `__pycache__/` from before record `110` -- an untracked build artifact no `git clean` in the
    # test's own instructions removes, so anyone whose working copy predates that record started
    # red on a tree that is in fact correct. What this rule forbids is an implementation living
    # there; bytecode left behind by one that used to is not that.
    modules = sorted(
        path.as_posix() for path in pathlib.Path("src/vqapr/_internal/extensions").glob("*.py")
    )
    assert not modules, (
        f"`_internal/extensions/` is back: {modules}. The extension authorities live in "
        "`vqapr/extension/` since record 110; putting an implementation back under `_internal` "
        "recreates the two-door problem docs/issues/029 records."
    )

    # `identity` is deliberately absent. It was the fifth promoted module, and record `124`
    # deleted it with the Project cluster: its only two importers were `registration_bridge` and
    # `venue_bridge`, both of which went the same way. What this asserts is that the four that
    # remain are still at their promoted paths, not that the original five all survived.
    for name in ("component", "fingerprint", "loading", "registration"):
        module = pathlib.Path(f"src/vqapr/extension/{name}.py")
        assert module.is_file(), f"{name} must live at vqapr/extension/{name}.py"


def test_the_promoted_modules_are_real_rather_than_forwarding() -> None:
    """They were four-line re-export shims. If one shrinks back to that, the move was undone.

    Deliberately a floor on substance rather than an exact size: the point is that these files hold
    the implementation, and a re-export shim cannot.
    """
    for name in ("component", "fingerprint", "loading", "registration"):
        source = pathlib.Path(f"src/vqapr/extension/{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        assert defined, (
            f"vqapr/extension/{name}.py defines nothing and is forwarding again; record 110 moved "
            "the implementation here so the temporary file could stop existing"
        )


def test_only_the_enumerated_modules_reach_internal() -> None:
    """The surviving discipline: `_internal` is not a general-purpose import target."""
    actual = {importer for importer, _ in _internal_imports()}

    added = sorted(actual - PERMITTED)
    removed = sorted(PERMITTED - actual)

    assert not added, (
        "these modules import `vqapr._internal` and are not permitted to:\n  "
        + "\n  ".join(added)
        + "\n\n`_internal` holds implementation detail and the shared primitives named in "
        "SHARED_PRIMITIVES. If you need a capability from it, either it belongs on a public "
        "surface or your module belongs on this list with a reason."
    )
    assert not removed, (
        "these modules no longer import `vqapr._internal`:\n  "
        + "\n  ".join(removed)
        + "\n\nUsually good news, but this list is the record of what the boundary is; update it "
        "in the same commit so the next reader is not comparing against a stale one."
    )


def test_every_internal_edge_is_a_shared_primitive_or_a_frozen_inheritance() -> None:
    """What each permitted importer is actually allowed to reach, not merely that it may reach.

    Without this, `PERMITTED` would be a blanket pass: a module admitted for `_internal.atomic`
    could quietly start importing anything else under `_internal`.
    """
    inherited = {
        # Frozen; its edges predate the freeze and may not grow.
        "src/vqapr/project.py",
        # The authoring seam, pending the convergence step.
        "src/vqapr/extension/loading.py",
    }
    unexplained = sorted(
        (importer, module)
        for importer, module in _internal_imports()
        if module not in SHARED_PRIMITIVES and importer not in inherited
    )

    assert not unexplained, (
        "these edges reach `_internal` for something other than a shared primitive:\n  "
        + "\n  ".join(f"{importer} -> {module}" for importer, module in unexplained)
        + "\n\nOnly the inherited edges above reach `_internal` for anything else. Everything "
        "else on PERMITTED is there for `_internal.filelock` or `_internal.atomic` specifically."
    )
