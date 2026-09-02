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

**The debt is paid, and `PERMITTED` is now just `PERMANENT`.** This file used to keep two sets
apart on purpose: the CLI and the shipped samples using the surface the facade exists to be, and a
second set of boundary violations held open with an expiry attached, which is where review `R7`
found them -- *"면제 목록에 넣어 두었고, 만료일이 없다"*. Both halves are now discharged.

**Record `124` closed six of the seven.** `project.py` and five of the six `_internal` bridges are
deleted, and the exemptions they held went with them. What remained was `strategy_bridge.py`, which
was always the one entry with a live importer outside the cluster (`extension/loading.py`) and so
the one that could never be closed by deleting anything.

**Record `125` closed the seventh, and not by deleting it either.** The bridge imported
`EconomicPortfolioIntent`, `PortfolioTarget`, `IntentSourceRef` and `NoDecision` from the facade in
order to STAMP an intent -- minting the UUID, rebuilding provenance, copying the account version.
Moving that stamping into `flow/simulation.py`, where the Flow already derived every one of those
values to check the bridge's copy of them, left the bridge with nothing to import. The file is
still there and still translates one call surface into the other; it simply no longer reaches up.

So every importer of `vqapr.public` under `src/` is now a module using the facade for exactly what
the facade is for. If this list ever grows again, the entry is a violation and not an exemption:
there is no longer a second set to put it in.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# The floor. These are not tolerated, they are correct: the facade is the CLI's supported surface,
# so the CLI and the code shipped to show users how to call it are the surface being used for its
# purpose. Nothing here expires, and nothing here should acquire an expiry -- if this set ever
# empties, the facade has no consumers and the question is whether it should exist at all.
PERMANENT: frozenset[str] = frozenset(
    {
        # Shipped sample code, written the way a user would write it -- which means reaching the
        # same surface a user reaches. Routing it below the facade would make the samples lie about
        # the product.
        "src/vqapr/agent/sample/exchange.py",
        "src/vqapr/agent/sample/journey.py",
        # The CLI itself, which is the product the facade exists for.
        "src/vqapr/cli/check.py",
        # `cli/register.py` left this list in record `112`: its declaration parsing moved to
        # `vqapr/declarations.py`, which imports the owning modules directly rather than the
        # facade. That is the count moving for the reason the trajectory predicted.
        "src/vqapr/cli/run.py",
    }
)

# One set now. Kept as a separate name because every assertion below reads it, and because a
# future exemption -- if one is ever justified -- should have to be added here deliberately rather
# than by widening `PERMANENT`, which means something narrower.
PERMITTED: frozenset[str] = PERMANENT


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
        "is; update it in the same commit so the next reader is not comparing against a stale one. "
        "Drop the entry from `PERMANENT`. Every remaining entry is a module using the facade "
        "for what the facade is for, so losing one means the facade lost a consumer it was built "
        "for, and that is worth a second look rather than a silent edit."
    )


def test_the_count_still_matches_the_ruling() -> None:
    """The number the ruling published, kept honest.

    Held separately from the membership test so a failure says which question is wrong: the count,
    or which modules make it up.

    **Where it went**, recorded rather than asserted: **12** when the ruling was written, **11**
    after record `112` moved `cli/register.py`'s declaration parsing into `vqapr/declarations.py`,
    **5** after record `124` deleted `project.py` and the five bridges reachable only from it, and
    **4** after record `125` took the facade import out of `strategy_bridge.py`.

    Four is `len(PERMANENT)`, which the ruling called the floor: two CLI verbs and two shipped
    samples calling the product's own supported surface. Record `105` wrote that floor as **6**
    and it is left here as a caution rather than repeated as a fact -- it itemized to five in the
    tree it measured, and one of those verbs has since left. A hand-carried number drifts from the
    list it summarizes, which is the argument for the note staying a note.

    Reaching the floor is not the same as reaching zero, and `0` was never the target: it came
    from a *string* count of 18 that the ruling itself repudiates
    (`docs/design/agent-first-surface.md`, "For completeness and to stop the earlier error being
    inherited silently"). A facade with no consumers would be a facade with no reason to exist.
    """
    assert len(_importers()) == 4


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
    text = pathlib.Path(path).read_text(encoding="utf-8")
    # Each file must still contain a `vqapr` import inside template text, or this test pins
    # nothing. `scaffold.py` stopped containing `vqapr.public` in record `131`: all three
    # templates now emit `from vqapr import authoring as va`, which is the convergence this
    # tripwire was waiting for, not a regression of it.
    assert "from vqapr" in text and ("vqapr.public" in text or "authoring as va" in text)
