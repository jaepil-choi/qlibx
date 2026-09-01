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

**The exemptions are not all the same kind of thing.** `PERMITTED` is the union of two sets kept
apart on purpose: `PERMANENT`, which is the CLI and the shipped samples using the surface the facade
exists to be, and `EXPIRING_AT_G008`, which is seven boundary violations tolerated for exactly as
long as `project.py` is in the tree. As one flat list it read as a single blanket permission with
the difference left in a comment, which is where review `R7` found it -- *"면제 목록에 넣어 두었고,
만료일이 없다"*. Split, the second kind carries its own expiry, and
`test_the_expiring_exemptions_expire_when_project_py_does` comes due on the day the gate opens.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# The file the expiring exemptions are tied to. `G008` -- delete `vqapr.public`, relocate the
# retained authorities, cut the breaking `0.2.0a1` -- takes it, and both of that goal's admission
# gates are still shut (`docs/design/agent-first-surface.md`, "The G008 admission conditions": the
# T0 trace/row comparator has not been run, and the owner has not approved the release). Named as a
# path rather than as a sentence so the test below can ask whether the gate has opened.
G008_DELETES = "src/vqapr/project.py"

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

# The debt. Every entry here is the violation this file exists to catch, held open rather than
# excused, and all seven are held open by the same fact: `project.py` is still in the tree. Bound to
# that fact structurally -- see `test_the_expiring_exemptions_expire_when_project_py_does`, which
# fails on the day `G008` deletes it and names what to delete alongside.
EXPIRING_AT_G008: frozenset[str] = frozenset(
    {
        # The six `_internal` bridges. Their whole job is to speak the facade's vocabulary, which is
        # why the import reads as reasonable -- but `_internal` sits BELOW the facade, so each of
        # these reaches back up through the thing it sits beneath. Five of them (constraint,
        # registration, run, schedule, venue) have exactly one importer anywhere in `src/` and it is
        # `project.py`; `strategy_bridge` is also reached from `extension/loading.py`, the shipped
        # path, which is why it is the only one of the six that can move before the gate opens.
        "src/vqapr/_internal/constraint_bridge.py",
        "src/vqapr/_internal/registration_bridge.py",
        "src/vqapr/_internal/run_bridge.py",
        "src/vqapr/_internal/schedule_bridge.py",
        "src/vqapr/_internal/strategy_bridge.py",
        "src/vqapr/_internal/venue_bridge.py",
        # `project.py` -- unshipped, zero lines executed on the product journey, and the reason the
        # six above are reachable at all.
        #
        # The justification that stood here was that it is *frozen by the same ruling*. The owner
        # ruling of 2026-09-01 retired that: there is no such thing as a frozen module, a module
        # that needs fixing is fixed, and whether the fix is right is settled by reviewing the merge
        # rather than by a standing prohibition (`test_the_frozen_cluster_gains_no_callers.py`
        # carries the ruling in full). So "it cannot move" is no longer a true sentence about this
        # file, and an exemption resting on it was resting on nothing.
        #
        # What survives the ruling is the date. `project.py` is not immovable; it is scheduled to
        # die at `G008`. That is a weaker claim and a more useful one: it makes this an exemption
        # with an expiry rather than a permission with an excuse.
        "src/vqapr/project.py",
    }
)

# The ruling's own list, as the union of the two. Sorted within each set so a diff reads cleanly.
PERMITTED: frozenset[str] = PERMANENT | EXPIRING_AT_G008


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
        "Drop the entry from whichever set holds it — out of `EXPIRING_AT_G008` is the debt being "
        "paid down, out of `PERMANENT` means the facade lost a consumer it was built for and is "
        "worth a second look."
    )


def test_the_count_still_matches_the_ruling() -> None:
    """The number the ruling published, kept honest.

    Held separately from the membership test so a failure says which question is wrong: the count,
    or which modules make it up.

    **The trajectory, recorded but deliberately not asserted.** Where this count goes, none of it an
    assertion here:

    * **11 today** — `len(PERMITTED)`. Six `_internal/*_bridge.py`, two shipped samples, two CLI
      verbs, `project.py`. It was 12 until record `112` moved `cli/register.py`'s declaration
      parsing into `vqapr/declarations.py`, which reaches the owning modules directly.
    * **10 after the authoring-convergence step**, which removes the facade import from
      `strategy_bridge` — the only one of the six with an importer outside `project.py`
      (`extension/loading.py`), and so the only one that can move while the gate is shut.
    * **`len(PERMANENT)` at `G008`**, when `project.py` and everything reachable only from it goes.
      Four today: two CLI verbs and two shipped samples calling the product's own supported surface,
      which is not a violation of anything. Written as the set rather than as a number, because the
      floor is not something a later reader should have to re-derive — it is whatever `PERMANENT`
      holds on the day the gate opens.

    Record `105` wrote that endpoint as **6** and it is left here as a caution rather than repeated
    as a fact: the floor it names in the same sentence — the CLI verbs and the shipped samples —
    itemized to five in the tree it measured, and one of those verbs has since left. A hand-carried
    number drifts from the list it is supposed to summarize, which is the argument for the note
    staying a note.

    Encoding the endpoint as an acceptance would fail this suite for every commit between here and
    `G008` — and `0` was never reachable at all: it came from a *string* count of 18 that the ruling
    itself repudiates (`docs/design/agent-first-surface.md`, "For completeness and to stop the
    earlier error being inherited silently"). The step that actually moves the number is the step
    that updates this assertion and the ruling's list together, in one commit.
    """
    assert len(_importers()) == 11


def test_the_expiring_exemptions_expire_when_project_py_does() -> None:
    """The expiry condition, executed rather than described.

    Review `R7`'s finding was not that the seven violations are exempt — it is that the exemption
    had no expiry date, so the list could outlive its reason without anything noticing. This is the
    date. It says nothing about whether `G008` should open, which is an owner approval no test can
    hold; it is the cleanup note, attached to the event that makes it due.

    It keys on `project.py` because that single file is the reason all seven are on a live path:
    five of the six bridges have no other importer in `src/`, and the sixth plus `project.py` itself
    go with the cluster. One fact, one condition, seven entries.
    """
    assert pathlib.Path(G008_DELETES).exists(), (
        f"`{G008_DELETES}` is gone, so `G008` has run and these "
        f"{len(EXPIRING_AT_G008)} exemptions expired with it:\n  "
        + "\n  ".join(sorted(EXPIRING_AT_G008))
        + f"\n\nDelete every one of them from `EXPIRING_AT_G008` — including the `{G008_DELETES}` "
        "entry and this condition itself — in the commit that deleted the file. Anything on that "
        "list still importing `vqapr.public` afterwards is a live violation to fix, not an "
        "exemption to re-grant: the reason it had one no longer exists."
    )


def test_an_exemption_is_permanent_or_expiring_and_never_both() -> None:
    """The split is only load-bearing if each entry sits on exactly one side of it.

    An entry in both sets is silently absorbed by the union, so `PERMITTED` would keep the module
    exempt while `EXPIRING_AT_G008` claims it is scheduled to go — the flat list's failure mode,
    reintroduced. Cheap to state, so it is stated.
    """
    both = sorted(PERMANENT & EXPIRING_AT_G008)

    assert not both, (
        "these modules are listed as permanently permitted AND as expiring at `G008`:\n  "
        + "\n  ".join(both)
        + "\n\nPick one. A module either calls the facade because that is what the facade is for, "
        "or it is a violation held open until `project.py` goes."
    )


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
