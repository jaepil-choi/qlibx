"""Phase F-10b — skill loader + skill cross-reference resolution.

Two assertions held by the in-package skill surface:

  * Every directory under ``echolon/native/skills/echolon_api/`` that
    contains a ``SKILL.md`` is discoverable via ``list_skills()`` and
    loadable via ``get_skill(name)``.
  * Every "the X skill" / "skill: X" cross-reference inside a SKILL.md
    body resolves to a real skill name (Phase F-10e — prevents the kind of
    dangling reference that bit ``llms.txt`` referencing the missing
    ``docs/ARCHITECTURE.md`` before F-7).
"""
from __future__ import annotations

import re
from pathlib import Path

from echolon.native.skills import Skill, get_skill, list_skills


_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "echolon" / "native" / "skills" / "echolon_api"


def test_list_skills_returns_at_least_the_orientation_set() -> None:
    names = set(list_skills())
    # Phase F-9b shipped these orientation skills; later phases may add more.
    must_have = {
        "quick_start",
        "component_guide",
        "api_reference",
        "config_reference",
        "patterns",
        "trading-api-core",
        "code-standards",
        "parameter-patterns",
    }
    missing = must_have - names
    assert not missing, f"orientation skills missing: {missing}"


def test_get_skill_round_trips_for_every_listed_name() -> None:
    for name in list_skills():
        s = get_skill(name)
        assert s is not None, f"list_skills includes {name!r} but get_skill returned None"
        assert isinstance(s, Skill)
        assert s.name == name
        assert s.body, f"{name}: SKILL.md is empty"


def test_get_skill_strips_yaml_frontmatter() -> None:
    s = get_skill("quick_start")
    assert s is not None
    assert s.body.startswith("---"), "expected YAML frontmatter to remain in 'body'"
    assert not s.body_no_frontmatter.startswith("---"), \
        "body_no_frontmatter should have the frontmatter stripped"
    assert s.description, "frontmatter description should be parsed out"


def test_get_skill_unknown_returns_none() -> None:
    assert get_skill("not_a_real_skill_xyz") is None


_REF_PATTERNS = [
    # "the X skill" / "the X skill —" / "the X skill\n"
    re.compile(r"\bthe\s+`?([a-z][a-z0-9_-]*?)`?\s+skill\b", re.IGNORECASE),
    # "skill: X" inline
    re.compile(r"\bskill:\s+`?([a-z][a-z0-9_-]+?)`?(?:\s|$|—|,|\.|\)|\])"),
    # markdown link: [name](../X/SKILL.md)
    re.compile(r"\]\((?:\.\./)?([a-z][a-z0-9_-]+)/SKILL\.md\)"),
]

# These are stop-words / generic mentions that aren't real skill references.
_REF_BLOCKLIST = {
    "any",
    "the",
    "a",
    "this",
    "each",
    "above",
    "echolon_api",
    "skill",  # "the skill" with no name
    "trs-paradigm",  # mentioned in prose, not a skill
}


def test_skill_cross_references_resolve() -> None:
    """Every "the X skill" / "skill: X" / SKILL.md link in any SKILL.md
    body must resolve to a real skill listed by ``list_skills()``."""
    known = set(list_skills())
    unresolved: list[tuple[str, str, str]] = []

    for name in known:
        s = get_skill(name)
        assert s is not None
        body = s.body_no_frontmatter
        for pattern in _REF_PATTERNS:
            for match in pattern.finditer(body):
                ref = match.group(1).strip()
                if ref.lower() in _REF_BLOCKLIST:
                    continue
                # Tolerate underscore-vs-hyphen variants (the skill index uses
                # both: ``trading-api-core`` vs ``trading_context``).
                normalized_candidates = {ref, ref.replace("-", "_"), ref.replace("_", "-")}
                if not (normalized_candidates & known):
                    unresolved.append((name, ref, match.group(0)))

    assert not unresolved, (
        f"{len(unresolved)} skill cross-references don't resolve:\n"
        + "\n".join(f"  in {src}: ref={ref!r} (matched: {matched!r})"
                    for src, ref, matched in unresolved[:10])
    )
