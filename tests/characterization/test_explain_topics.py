"""Every `explain` topic resolves to a skill section, and every skill section is referenced.

The `explain` field points at the part of `agent/skill/SKILL.md` that says why a whole class of
refusal happens and how to stop causing it. That makes the enum and the document **co-owned**: the
package decides which topic a refusal carries, and the skill decides what the reader finds when
they follow it.

Co-ownership without a check is how the two drift. A topic renamed in the enum leaves a section
nobody reaches; a section renamed in the document leaves a topic pointing at nothing. Neither
raises anything at runtime -- the reader simply follows a pointer into empty space, which is worse
than no pointer, because it spends their trust before it fails them.

So the check runs in **both directions**. One direction alone is the easy mistake: asserting only
that every topic resolves would let a section accumulate that no refusal ever reaches, which is
documentation that looks maintained and is not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vqapr.domain.errors import ExplainTopic

SKILL = Path(__file__).resolve().parents[2] / "src" / "vqapr" / "agent" / "skill" / "SKILL.md"

_SECTION = re.compile(r"^### Recovering from:\s*(\S+)\s*$", re.MULTILINE)


def _documented_topics() -> list[str]:
    if not SKILL.is_file():
        raise FileNotFoundError(f"the skill this enum is co-owned with is missing: {SKILL}")
    return _SECTION.findall(SKILL.read_text(encoding="utf-8"))


def test_every_topic_resolves_to_a_skill_section() -> None:
    """A refusal must never point the reader at a section that does not exist."""
    documented = set(_documented_topics())
    unresolved = sorted(str(topic) for topic in ExplainTopic if str(topic) not in documented)

    assert unresolved == [], (
        f"{len(unresolved)} explain topic(s) point at a section SKILL.md does not have: "
        f"{unresolved}. Add the section or remove the topic."
    )


def test_every_skill_section_is_reachable_from_a_topic() -> None:
    """The other direction: a section no refusal reaches is documentation nobody is sent to."""
    topics = {str(topic) for topic in ExplainTopic}
    orphaned = sorted(name for name in _documented_topics() if name not in topics)

    assert orphaned == [], (
        f"{len(orphaned)} SKILL.md section(s) are unreachable, because no ExplainTopic names "
        f"them: {orphaned}. Remove the section or add the topic."
    )


def test_the_enumeration_is_closed_against_free_strings() -> None:
    """`explain` is a topic, not a string, so a typo cannot reach a published refusal.

    A free-string field would let `\"declaraton-shape\"` ship and resolve to nothing. The type is
    what makes the two directions above checkable at all.
    """
    from vqapr.domain.errors import Failure

    with pytest.raises(TypeError, match="explain must be an ExplainTopic"):
        Failure.bounded(
            "probe.closed_enum",
            "a refusal must carry a topic from the closed set",
            fix="pass an ExplainTopic member",
            explain="declaration-shape",  # type: ignore[arg-type]
        )


def test_each_documented_section_says_something() -> None:
    """A heading with no body resolves, and still tells the reader nothing.

    This is the failure the two directional tests above cannot see: both would pass on seven empty
    sections.
    """
    text = SKILL.read_text(encoding="utf-8")
    empty: list[str] = []
    for match in _SECTION.finditer(text):
        rest = text[match.end() :]
        body = rest.split("\n### ", 1)[0].split("\n## ", 1)[0]
        if len(body.strip()) < 200:
            empty.append(match.group(1))

    assert empty == [], f"explain section(s) with no usable guidance: {empty}"
