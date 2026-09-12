"""`status` is a closed set, and no shipped skill may carry a per-status catalogue.

## What this file used to assert, and why it stopped

It asserted that every `Status` member had a `### Recovering from: <number> <label>` section in the
skill, and that every such section reached a member -- the enum and the document co-owned, checked
in both directions so neither could drift into a pointer aimed at empty space.

PRD §11.2 retired the co-ownership. A refusal now carries `status` (who must act), `stage` (where
it closed) and `cause` (what happened), beside `fix`, `requirement`, `observed` and `source`; prose
restating those duplicates what the envelope already says and goes stale every release, which
`docs/issues/archive/025`, `030` and `067` each are. The 219 lines of catalogue were deleted with the
split, having moved the four things the envelope genuinely cannot carry into the skills that own
them.

## What replaced it

The mirror image. The old direction guarded against a status with no section; the new one guards
against a section coming back -- because the reasoning for deleting it lives in a PRD section and a
record, and neither is consulted while someone is writing a helpful-looking paragraph.

`test_the_status_set_is_closed_against_free_strings` is unchanged: it was never about the sections.
It is what makes `status` branchable at all, and it is the reason the deleted catalogue could be
deleted without losing the classification.

The enum is read from `domain/errors.py`'s source rather than imported, so this file runs while the
package's raise sites are mid-migration and `import vqapr` may not.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from vqapr.agent.skillset import shipped_skills

REPO = Path(__file__).resolve().parents[2]
ERRORS = REPO / "src" / "vqapr" / "domain" / "errors.py"

_SECTION = re.compile(r"^#{2,4} Recovering from:\s*(\d{3})", re.MULTILINE)


def _status_members() -> dict[int, str]:
    """`{number: lowercase label}` read from the enum's source."""
    tree = ast.parse(ERRORS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Status":
            members = {
                int(statement.value.value): statement.targets[0].id.lower()
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, int)
                and isinstance(statement.targets[0], ast.Name)
            }
            assert members, f"{ERRORS}: class Status declares no integer members"
            return members
    raise AssertionError(f"{ERRORS}: no class Status found")


def test_no_shipped_skill_carries_a_per_status_catalogue() -> None:
    """PRD §11.2: failure recovery is not a skill.

    A `Recovering from: 4xx` heading is the shape the deleted 219 lines had, and it is the shape
    a well-meant reintroduction would take. Finding one means either the decision was reversed --
    in which case the PRD says so and this test should go with it -- or it was forgotten.
    """
    offenders = [
        f"{name}/{path}"
        for name, files in shipped_skills().items()
        for path, content in files.items()
        if path.endswith(".md") and _SECTION.search(content.decode("utf-8"))
    ]
    assert offenders == [], (
        f"per-status recovery sections are back in {offenders}. The envelope carries status, "
        "stage, cause, fix, requirement, observed and source; prose restating them goes stale "
        "every release (docs/issues/archive/025, 030, 067)."
    )


def test_every_status_still_has_a_name_and_a_number() -> None:
    """The classification survived the deletion, which is what made deleting it safe.

    `reading-the-envelope.md` teaches 4xx versus 5xx and the order to branch in; that is
    orientation and does not enumerate. This asserts the set it orients around is still there.
    """
    members = _status_members()
    assert members, "the Status enum is empty"
    assert all(100 <= number < 600 for number in members), members
    assert any(400 <= number < 500 for number in members), "no 4xx: nothing is the caller's fault"
    assert any(500 <= number < 600 for number in members), "no 5xx: nothing is ours"


def test_the_status_set_is_closed_against_free_strings() -> None:
    """`status` is a `Status`, not an int and not a string, so a typo cannot reach a refusal.

    A free field would let `status=404` or `status="missing"` ship and mean nothing. The type is
    what makes branching on `status` sound, and it is unchanged by the split.
    """
    from vqapr.domain.errors import Failure

    with pytest.raises(TypeError, match="status must be a Status"):
        Failure.bounded(
            "probe.closed_enum",
            "a refusal must carry a status from the closed set",
            status="missing",  # type: ignore[arg-type]
            fix="pass a Status member",
        )
    with pytest.raises(TypeError, match="status must be a Status"):
        Failure.bounded(
            "probe.closed_enum",
            "a refusal must carry a status from the closed set",
            status=404,  # type: ignore[arg-type]
            fix="pass a Status member",
        )
