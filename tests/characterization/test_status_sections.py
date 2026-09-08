"""Every `Status` member has a skill section, and every skill section names a `Status` member.

A refusal's `status` is the first thing an agent branches on (record `171`), and the skill's
`### Recovering from: <number> <label>` sections are where it is sent for what that status means
and how to stop hitting it. That makes the enum and the document **co-owned**: the package
decides which status a refusal carries, and the skill decides what the reader finds when they
follow it.

Co-ownership without a check is how the two drift. A member added to the enum leaves a status no
section explains; a section renamed in the document leaves a status pointing at nothing. Neither
raises anything at runtime -- the reader simply follows a pointer into empty space, which is
worse than no pointer, because it spends their trust before it fails them.

So the check runs in **both directions**. One direction alone is the easy mistake: asserting only
that every status resolves would let a section accumulate that no refusal ever reaches, which is
documentation that looks maintained and is not.

The enum is read from `domain/errors.py`'s source rather than imported, so this file runs while
the package's raise sites are mid-migration and `import vqapr` may not.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "src" / "vqapr" / "agent" / "skill" / "SKILL.md"
ERRORS = REPO / "src" / "vqapr" / "domain" / "errors.py"

_SECTION = re.compile(r"^### Recovering from:\s*(\d{3}) ([a-z]+)\s*$", re.MULTILINE)


def _status_members() -> dict[int, str]:
    """`{400: "invalid", 404: "missing", ...}`: number -> `Status.label`, from the source."""
    tree = ast.parse(ERRORS.read_text(encoding="utf-8"), filename=str(ERRORS))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Status":
            members = {
                statement.value.value: statement.targets[0].id.lower()
                for statement in node.body
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, int)
            }
            assert members, f"{ERRORS}: class Status declares no integer members"
            return members
    raise AssertionError(f"{ERRORS}: no class Status found")


def _documented_sections() -> list[tuple[int, str]]:
    if not SKILL.is_file():
        raise FileNotFoundError(f"the skill this enum is co-owned with is missing: {SKILL}")
    return [(int(number), label) for number, label in _SECTION.findall(SKILL.read_text("utf-8"))]


def test_every_status_resolves_to_a_skill_section() -> None:
    """A refusal must never carry a status the skill has no section for."""
    documented = set(_documented_sections())
    unresolved = sorted(
        f"{number} {label}"
        for number, label in _status_members().items()
        if (number, label) not in documented
    )

    assert unresolved == [], (
        f"{len(unresolved)} Status member(s) have no `### Recovering from: <number> <label>` "
        f"section in SKILL.md: {unresolved}. Add the section or remove the member."
    )


def test_every_skill_section_is_reachable_from_a_status() -> None:
    """The other direction: a section no refusal reaches is documentation nobody is sent to."""
    members = _status_members()
    orphaned = sorted(
        f"{number} {label}"
        for number, label in _documented_sections()
        if members.get(number) != label
    )

    assert orphaned == [], (
        f"{len(orphaned)} SKILL.md section(s) are unreachable, because no Status member has "
        f"that number and label: {orphaned}. Remove the section or add the member."
    )


def test_the_sections_are_one_per_status() -> None:
    """Two sections for one status would send the reader to whichever one the regex found first."""
    numbers = [number for number, _ in _documented_sections()]
    duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
    assert duplicated == [], f"status(es) documented more than once: {duplicated}"


def test_the_status_set_is_closed_against_free_strings() -> None:
    """`status` is a `Status`, not an int and not a string, so a typo cannot reach a refusal.

    A free field would let `status=404` or `status="missing"` ship and resolve to no section.
    The type is what makes the two directions above checkable at all.
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


def test_each_documented_section_says_something() -> None:
    """A heading with no body resolves, and still tells the reader nothing.

    This is the failure the directional tests above cannot see: they would pass on nine empty
    sections.
    """
    text = SKILL.read_text(encoding="utf-8")
    empty: list[str] = []
    for match in _SECTION.finditer(text):
        rest = text[match.end() :]
        body = rest.split("\n### ", 1)[0].split("\n## ", 1)[0]
        if len(body.strip()) < 200:
            empty.append(f"{match.group(1)} {match.group(2)}")

    assert empty == [], f"status section(s) with no usable guidance: {empty}"
