"""The facade boundary, as a test rather than as prose.

`docs/design/agent-first-surface.md` ("The ruling -- 2026-08-28") defines exactly one instrument for
this boundary: the count of modules under `src/` containing a **real import** of `vqapr.public`,
excluding occurrences inside string literals. It records a verified value of 12 and names all
twelve. It also gives the AST command to re-measure it.

What it did not have was a test. `docs/issues/028` is what that cost: `fix/015a-extract-judgments`
moved the judgments below the CLI and let them keep importing the facade, taking the count to 13,
and the whole 1,400-test suite stayed green, because the tripwire lived in a document nobody
executes.
The regression was found by an owner-requested audit, not by the mechanism meant to catch it.

`vqapr.public` is the CLI's supported implementation surface and sits **above** `flow/`, `domain/`,
`workspace/` and the rest. A module in those layers importing it reaches back up through the thing
it is supposed to sit beneath -- and the import still works, so nothing fails until someone reads
for it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# The ruling's own list, verbatim. Sorted so a diff reads cleanly.
PERMITTED: frozenset[str] = frozenset(
    {
        # The six `_internal` bridges: their whole job is to speak the facade's vocabulary.
        "src/vqapr/_internal/constraint_bridge.py",
        "src/vqapr/_internal/registration_bridge.py",
        "src/vqapr/_internal/run_bridge.py",
        "src/vqapr/_internal/schedule_bridge.py",
        "src/vqapr/_internal/strategy_bridge.py",
        "src/vqapr/_internal/venue_bridge.py",
        # Shipped sample code, which is written the way a user would write it.
        "src/vqapr/agent/sample/exchange.py",
        "src/vqapr/agent/sample/journey.py",
        # The CLI itself, which is the product the facade exists for.
        "src/vqapr/cli/check.py",
        # `cli/register.py` left this list in record `112`: its declaration parsing moved to
        # `vqapr/declarations.py`, which imports the owning modules directly rather than the
        # facade. That is the count moving for the reason the trajectory predicted.
        "src/vqapr/cli/run.py",
        # Unshipped and frozen by the same ruling.
        "src/vqapr/project.py",
    }
)


def _importers() -> set[str]:
    """Every module under `src/` with a real `vqapr.public` import.

    An AST walk rather than a text search, because `cli/new.py` and `extension/scaffold.py` both
    contain `vqapr.public` inside the templates they emit. Those are `Constant` nodes and are
    structurally invisible here, which is exactly why the ruling specifies an AST walk: a string
    count moves when a template is edited, for reasons that have nothing to do with the boundary.
    """
    found: set[str] = set()
    for path in pathlib.Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported_from = (
                isinstance(node, ast.ImportFrom) and (node.module or "") == "vqapr.public"
            )
            imported = isinstance(node, ast.Import) and any(
                alias.name == "vqapr.public" for alias in node.names
            )
            if imported_from or imported:
                found.add(path.as_posix())
    return found


def test_no_module_below_the_cli_reaches_up_to_the_facade() -> None:
    """The tripwire itself, naming what moved rather than only that something did."""
    actual = _importers()

    added = sorted(actual - PERMITTED)
    removed = sorted(PERMITTED - actual)

    assert not added, (
        "these modules import `vqapr.public` and are not permitted to:\n  "
        + "\n  ".join(added)
        + "\n\nThe facade is the CLI's supported surface and sits ABOVE these layers. Import the "
        "class from where it is defined -- `vqapr.workspace`, `vqapr.domain.*`, `vqapr.flow.*` -- "
        "as `flow/preflight.py` does. If this import is genuinely correct, the ruling in "
        "docs/design/agent-first-surface.md has to change first, and this list with it."
    )
    assert not removed, (
        "these modules no longer import `vqapr.public`:\n  "
        + "\n  ".join(removed)
        + "\n\nThat is usually good news, but the ruling's list is the record of what the boundary "
        "is; update it in the same commit so the next reader is not comparing against a stale one."
    )


def test_the_count_still_matches_the_ruling() -> None:
    """The number the ruling published, kept honest.

    Held separately from the membership test so a failure says which question is wrong: the count,
    or which modules make it up.

    **The trajectory, recorded but deliberately not asserted.** The structural plan takes this count
    12 -> 10 -> 6, and none of that is an assertion here:

    * **11 today.** Six `_internal/*_bridge.py`, two shipped samples, two CLI verbs, `project.py`.
      It was 12 until record `112` moved `cli/register.py`'s declaration parsing into
      `vqapr/declarations.py`, which reaches the owning modules directly.
    * **10 after the authoring-convergence step**, which removes the facade import from the two
      bridges on the shipped path (`strategy_bridge`, `pit_bridge`). The other four bridges are
      reachable only from frozen `project.py` and cannot move before `G008`.
    * **6 only at `G008`**, when the frozen cluster goes. The floor is the CLI and its shipped
      samples calling the product's own supported surface, which is not a violation of anything.

    A note, not a gate. Encoding 6 as an acceptance would fail this suite for every commit between
    here and `G008` — and `0` was never reachable at all: it came from a *string* count of 18 that
    the ruling itself repudiates (`docs/design/agent-first-surface.md`, "For completeness and to
    stop the earlier error being inherited silently"). The step that actually moves the number is
    the step that updates this assertion and the ruling's list together, in one commit.
    """
    assert len(_importers()) == 11


@pytest.mark.parametrize(
    "path",
    ["src/vqapr/cli/new.py", "src/vqapr/extension/scaffold.py"],
)
def test_template_text_is_not_counted_as_an_import(path: str) -> None:
    """The exclusion the AST walk exists for, pinned so it cannot silently start counting.

    Both files contain `vqapr.public` inside scaffold templates. If either ever appears in the
    importer set, the measurement has regressed to a string count -- the failure mode the ruling
    devotes a paragraph to.
    """
    assert path not in _importers()
    assert "vqapr.public" in pathlib.Path(path).read_text(encoding="utf-8")
