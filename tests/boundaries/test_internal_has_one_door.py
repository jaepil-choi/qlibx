"""One door into `_internal/extensions`, as a test rather than as four docstrings.

`docs/issues/029` is what the prose cost. Four modules under `extension/` are forwarding adapters
over `_internal/extensions/`, and each says it will be deleted -- so three call sites reasoned that
a module scheduled to die should not be grown, imported `_internal` directly, and produced a tree
where the same four authorities are reached by two names depending on which file you are reading.

The reasoning is backwards, and that is the point worth pinning. A deletion whose callers all name
one path is four files removed and every stale import breaking loudly at import time. A deletion
reached by two paths is a grep, and it is complete when somebody says it is.

This does not judge whether `_internal` should be reachable at all, and it does not touch the
admission conditions for the deletion itself -- those are in `docs/design/agent-first-surface.md`
("The G008 admission conditions"). It watches one number: which modules outside `_internal/` name
it. `tests/` are deliberately out of scope; they are allowed to test the physical home directly, and
`tests/extension/test_agent_first_internal_routes.py` exists to do exactly that.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import vqapr._internal.extensions.loading as internal_loading
import vqapr.extension.loading as adapter_loading

INTERNAL_ROOT = "src/vqapr/_internal/"

# Why each of these is allowed to name `_internal`, one reason per entry.
PERMITTED: frozenset[str] = frozenset(
    {
        # The four forwarding adapters. Naming `_internal` is their whole content.
        "src/vqapr/extension/component.py",
        "src/vqapr/extension/fingerprint.py",
        "src/vqapr/extension/loading.py",
        "src/vqapr/extension/registration.py",
        # Frozen by `docs/design/agent-first-surface.md`: unshipped, no new callers, and not to be
        # edited to serve a new requirement. Its `_internal` imports are inherited, not new.
        "src/vqapr/project.py",
    }
)

SHARED_PRIMITIVES: frozenset[str] = frozenset(
    {
        # Not extension authorities, and not scheduled for deletion. These are the modules the
        # structural refactoring is consolidating INTO: one exclusive mutex (record `106`) and one
        # durable write (record `107`), each replacing several copies that had drifted apart.
        "vqapr._internal.filelock",
        "vqapr._internal.atomic",
    }
)
"""`_internal` modules any layer may import directly.

**Why this list exists, and why it is not a hole in the rule.** The one-door rule is about the
extension *authorities*: `_internal/extensions/*` must be reached through `extension/*` so that
deleting the four adapters stays mechanical -- four files removed and every stale import breaking
loudly, rather than a grep. When record `098` wrote it, the only `_internal` importers outside
`_internal/` were those adapters and `project.py`, so "imports `_internal`" and "reaches an
extension authority" were the same set and the test could check the cheaper one.

They stopped being the same set the moment the refactoring started extracting shared primitives
into `_internal/`. Checking the broad property would have meant appending an exception per step,
and a rule with a growing exception list is one nobody can state. So the test now checks what the
rule always meant, and this list is the other half of it -- enumerated, not a wildcard, so adding
a third shared primitive is still a decision somebody takes on purpose.
"""


def _internal_imports() -> set[tuple[str, str]]:
    """Every `(importer, module)` edge from outside `_internal/` into it.

    An AST walk for the same reason the facade tripwire uses one: the string `vqapr._internal`
    appears in docstrings and refusal text, and a text count would move when a sentence is edited.
    Function-local imports count -- `cli/show.py` reached `_internal` from inside a function body,
    and a check that only read module headers would have called that file clean.
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
                    # `from vqapr._internal import atomic, filelock` names the package, and the
                    # submodule is the alias. Resolving it is what lets a shared primitive be
                    # distinguished from an authority at all, since both spell their package the
                    # same way.
                    for alias in node.names:
                        found.add((posix, f"{module}.{alias.name}"))
                else:
                    found.add((posix, module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("vqapr._internal"):
                        found.add((posix, alias.name))
    return found


def _internal_importers() -> set[str]:
    """Importers of anything in `_internal/` except the enumerated shared primitives."""
    return {
        importer
        for importer, module in _internal_imports()
        if module not in SHARED_PRIMITIVES
    }


def test_a_shared_primitive_is_reached_directly_and_an_authority_is_not() -> None:
    """The distinction the rule rests on, asserted so it cannot be blurred by a later entry.

    A shared primitive may be imported from anywhere. An extension authority may not, ever, no
    matter which module wants it -- including the modules on this list.
    """
    authority_edges = sorted(
        (importer, module)
        for importer, module in _internal_imports()
        if module.startswith("vqapr._internal.extensions")
        and importer not in PERMITTED
    )

    assert not authority_edges, (
        "these modules reach an extension authority directly:\n  "
        + "\n  ".join(f"{importer} -> {module}" for importer, module in authority_edges)
        + "\n\nNo shared-primitive allowance covers `_internal.extensions.*`. Reach it through "
        "`vqapr.extension.component`, `.fingerprint`, `.loading` or `.registration`."
    )


def test_only_the_adapters_reach_internal_extensions() -> None:
    """The tripwire, naming which module moved rather than only that the count did."""
    actual = _internal_importers()

    added = sorted(actual - PERMITTED)
    removed = sorted(PERMITTED - actual)

    assert not added, (
        "these modules import `vqapr._internal` directly and are not permitted to:\n  "
        + "\n  ".join(added)
        + "\n\nReach the extension authorities through `vqapr.extension.component`, "
        "`.fingerprint`, `.loading` or `.registration`, as `flow/preflight.py` and "
        "`cli/register.py` do. If the name you need is not re-exported yet, add it to the "
        "adapter's `__all__` -- keeping the forwarding surface complete is what that module is "
        "for, and it is what makes the eventual deletion mechanical rather than a grep "
        "(docs/issues/029)."
    )
    assert not removed, (
        "these modules no longer import `vqapr._internal`:\n  "
        + "\n  ".join(removed)
        + "\n\nUsually good news, but this list is the record of what the boundary is; update it "
        "in the same commit so the next reader is not comparing against a stale one."
    )


def test_the_adapter_forwards_every_name_a_caller_needs() -> None:
    """The half of the fix that is not a deletion.

    `as_loaded_fingerprint` was the one loading name the adapter did not re-export, which is why
    `public.py` imported it from `_internal` while importing its three neighbours from the adapter.
    An identity check, not a hasattr: the adapter must hand back the same object, so there is one
    authority reached by one name rather than two implementations that agree today.
    """
    assert adapter_loading.as_loaded_fingerprint is internal_loading.as_loaded_fingerprint
    assert "as_loaded_fingerprint" in adapter_loading.__all__


@pytest.mark.parametrize(
    "path",
    [
        "src/vqapr/extension/component.py",
        "src/vqapr/extension/fingerprint.py",
        "src/vqapr/extension/loading.py",
        "src/vqapr/extension/registration.py",
        "src/vqapr/_internal/extensions/component.py",
        "src/vqapr/_internal/extensions/fingerprint.py",
        "src/vqapr/_internal/extensions/loading.py",
        "src/vqapr/_internal/extensions/registration.py",
    ],
)
def test_the_deletion_note_cites_a_document_and_not_a_goal_id(path: str) -> None:
    """The expired-label half of `docs/issues/029`.

    All eight files pinned their deletion to `G004`. That id has been reassigned twice: in
    `gjc-handoff/session-03/goals.json` it is a completed goal about Project transactions, and the
    goal that owns this deletion is `G008`. A reader who looked it up found a finished goal about
    something else and could reasonably conclude the deletion had happened.

    So the note names a document instead. `docs/design/agent-first-surface.md` is in
    `.agent/project.yaml`'s canonical set and will still be findable after the next renumbering;
    a bare goal id in a docstring has now expired twice.

    The reference is matched as a word so `G008` inside the cited section title is not what fails
    this -- what fails it is a docstring that pins the deletion to an id again.
    """
    text = pathlib.Path(path).read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(text)) or ""

    stale = [token for token in ("G002", "G004") if token in docstring]
    assert not stale, (
        f"{path} pins its internal-transition note to {', '.join(stale)}. Goal ids in source "
        "comments have expired twice; cite docs/design/agent-first-surface.md instead."
    )
    assert "docs/design/agent-first-surface.md" in docstring, (
        f"{path} must name the document that carries the one-door rule and the deletion's "
        "admission conditions, so the note survives the next renumbering."
    )
