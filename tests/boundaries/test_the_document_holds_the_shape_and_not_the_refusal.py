"""The document is its own file, and the refusals moved once it was safe to move them.

Record `117`. `workspace.py` was 2,227 lines and the plan called for splitting it four ways. Only
the codec split was taken, and this file used to pin the measurement that decided it: an attempt
that moved `Workspace` away from `_workspace_error` measured **0 refusal codes added and 37
removed** -- every `workspace.dataset.*`, `workspace.agenda.*`, `workspace.component.*`,
`workspace.source.*` code and `dataset.register.span.absent` -- with a green test suite and a clean
lint. Four repairs were tried and none restored them.

**That constraint expired, and record `194` split the module.** The cost was never the split; it
was the resolver. `tests/characterization/refusal_codes.py` folds a `code` argument forwarded
through a helper, and until record `171` its index was per-file, so a helper in another module was
opaque and the codes silently left the baseline. Record `171` rebuilt `_SourceIndex` over every
module under `src/vqapr` at once, and says so in the past tense:

    A per-file index only ever resolved a code forwarded through a helper defined in the same
    file, so splitting a module dropped codes from the baseline.

The layering campaign measured that before moving anything rather than trusting the docstring
(`docs/refactoring/2026-09-08-the-layering-campaign.md` section 5): `_workspace_error` moved to a
probe module with its twenty-six callers left behind, and
`pytest tests/characterization/test_refusal_codes.py` reported **gained 0, lost 0**, with all 22
codes passed to it as literals still present. The probe was reverted and the real move followed.

**So what does this file still guard?** Not "the constructor stays with its callers" -- that
assertion is deleted, and deleting it is the point of this rewrite; leaving it would have made the
next reader restore a constraint the tree no longer has. What remains is the property the split was
*for*, which record `117` also stated and which nothing has retired: the document's shapes live in
one file that a later step can discard as a region, and that file raises no refusal of its own.

The second half is worth keeping even though the inventory could now follow a codec refusal. A
codec that raises is a codec that has opinions about validity, and `workspace/declarations.py` exists so
that pydantic holds the shape and `workspace/registration.py` holds the argument about what a wrong
shape means to a user. The assertion is about that division, not about the baseline any more.
"""

from __future__ import annotations

import ast
import pathlib

DOCUMENT = pathlib.Path("src/vqapr/workspace/declarations.py")
REFUSALS = pathlib.Path("src/vqapr/workspace/refusals.py")


def _constructs_a_failure(path: pathlib.Path) -> list[str]:
    """Functions in `path` that build a `Failure` directly."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "bounded"
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id == "Failure"
            ):
                found.append(node.name)
                break
    return found


def test_the_document_constructs_no_refusal() -> None:
    """The codec holds the shape; the layer above it holds what a wrong shape means."""
    raising = _constructs_a_failure(DOCUMENT)

    assert not raising, (
        "these codec functions construct a Failure: "
        + ", ".join(raising)
        + ". `workspace/declarations.py` declares what the document IS -- pydantic refuses a wrong shape "
        "and `workspace/registration.py` turns that into a refusal an agent can parse. A codec that "
        "raises its own has started deciding what a wrong shape means to a user."
    )


def test_the_refusal_constructor_is_one_function_in_one_place() -> None:
    """Twenty-odd project refusals still funnel through one constructor.

    What moved is where it lives, not how many there are of it. A second constructor beside it --
    or a `Failure.bounded` raised inline in `registry.py` -- is how a layer ends up with two refusal
    vocabularies, which is the thing record `171` spent a rebuild removing.
    """
    source = REFUSALS.read_text(encoding="utf-8")

    assert "def _workspace_error(" in source, (
        "`_workspace_error` left `workspace/refusals.py`. It may live anywhere the project layer can "
        "reach -- the refusal-code inventory has followed cross-module forwarding since record "
        "`171` -- but it must be one function, and this file is where the layer keeps it."
    )

    for module in ("registry.py", "merge.py", "references.py"):
        path = DOCUMENT.parent / module
        inline = _constructs_a_failure(path)
        assert not inline, (
            f"{module} builds a Failure directly in: {', '.join(inline)}. Raise through "
            "`_workspace_error` so the project layer keeps one refusal shape."
        )


def test_the_document_is_the_region_a_later_step_can_discard() -> None:
    """The point of the original split: the legacy document shapes are all in one file.

    A step that retires a legacy shape should be able to delete a region rather than hunt across a
    module for the three places it was handled.
    """
    source = DOCUMENT.read_text(encoding="utf-8")

    # Record `145` replaced the hand-written `_decode` / `_encode` with pydantic models and one
    # read and one write function; the property is the same -- the document's every shape, the
    # legacy ones included, is declared in one file.
    for marker in ("read_workspace", "write_workspace", "class WorkspaceDocument"):
        assert marker in source, f"{marker} belongs in the document module"

    assert "legacy" in source, (
        "the legacy document shapes are what this file exists to keep together; if they moved, the "
        "split stopped paying for itself"
    )
