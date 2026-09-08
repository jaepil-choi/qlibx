"""The workspace document is its own file, and the refusing half deliberately is not.

Record `117`. `workspace.py` was 2,227 lines and the plan called for splitting it four ways. Only
the codec split was taken, and this file pins the measurement that decided it — because the obvious
next step is for someone to "finish the job" and silently delete a third of the refusal inventory.

**What the inventory needs.** `tests/characterization/refusal_codes.py` resolves a refusal code by
folding f-string expressions through at most one or two levels of **local, same-file** helper
indirection. Every workspace refusal reaches `Failure.bounded` through the module-level
`_workspace_error`, and the stage constants it interpolates must be module-level literals in that
same file. `workspace.py` already said so about the constants:

    A module-level literal is what lets the refusal-code inventory fold `f"{SPAN_STAGE}.absent"`
    statically; an alias to another module's constant is opaque to that pass and the code would drop
    out of the inventory silently.

(Record `171` retired the interpolated stage constants: a code is now a plain literal and the
stage a `Stage` member, so the literal-constant guard below that pinned them is gone. The
same-file `_workspace_error` funnel is still what the inventory resolves through.)

**What that costs a split.** The resolver unions all callers of a parameter, so one unresolvable
caller collapses the entire set. An attempt that moved `Workspace` away from `_workspace_error`
measured **0 codes added and 37 removed** — every `workspace.dataset.*`, `workspace.agenda.*`,
`workspace.component.*`, `workspace.source.*` and `dataset.register.span.absent` code — with a green
test suite and a clean lint. Four repairs were tried and none restored them.

So the converting half moved and the refusing half stayed. The tests below are the guard rails on
that decision.
"""

from __future__ import annotations

import ast
import pathlib

CODEC = pathlib.Path("src/vqapr/workspace_document.py")
WORKSPACE = pathlib.Path("src/vqapr/workspace.py")


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


def test_the_codec_constructs_no_refusal() -> None:
    """The property that made this split safe, asserted so it stays true.

    A codec function that starts raising directly would be invisible to the inventory the moment it
    did, because it is no longer in the file that owns `_workspace_error`.
    """
    raising = _constructs_a_failure(CODEC)

    assert not raising, (
        "these codec functions construct a Failure: "
        + ", ".join(raising)
        + ". The refusal-code inventory folds codes through same-file indirection only, so a "
        "refusal raised here is a refusal that disappears from the baseline. Raise through "
        "`_workspace_error` in `workspace.py`, or move the function back."
    )


def test_the_error_constructor_still_lives_with_its_callers() -> None:
    """`_workspace_error` and every caller must stay in one file.

    This is the assertion that fails if someone finishes the four-way split as originally planned.
    """
    source = WORKSPACE.read_text(encoding="utf-8")

    assert "def _workspace_error(" in source, (
        "`_workspace_error` left `workspace.py`. Moving it measured 37 refusal codes removed from "
        "the baseline, with a green suite and clean lint, because the inventory cannot follow a "
        "cross-module hop."
    )
    assert source.count("_workspace_error(") > 20, (
        "the callers left `workspace.py` while the constructor stayed, which loses the inventory "
        "the same way round"
    )


def test_the_codec_is_the_region_a_later_step_can_discard() -> None:
    """The point of the split: the legacy document shapes are all in one file.

    A step that retires a legacy shape should be able to delete a region rather than hunt across a
    2,227-line module for the three places it was handled.
    """
    source = CODEC.read_text(encoding="utf-8")

    # Record `145` replaced the hand-written `_decode` / `_encode` with pydantic models and one
    # read and one write function; the property is the same -- the document's every shape, the
    # legacy ones included, is declared in one file.
    for marker in ("read_workspace", "write_workspace", "class WorkspaceDocument"):
        assert marker in source, f"{marker} belongs in the document module"

    assert "legacy" in source, (
        "the legacy document shapes are what this file exists to keep together; if they moved, the "
        "split stopped paying for itself"
    )
