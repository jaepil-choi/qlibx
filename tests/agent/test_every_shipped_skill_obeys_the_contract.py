"""PRD §11.2's rules for a skill, enforced on every skill as it lands.

These are cheap and mechanical, and they exist because the set is being built one skill at a time:
a rule kept by hand across nine directories is a rule that holds for the first three.

The rules are not stylistic. Each one has a failure mode behind it:

- **description says what AND when** -- only name and description are preloaded, so a description
  that does not say when to reach for the skill is the difference between being found and not
  existing. This is the defect that started the split.
- **body under 500 lines** -- the whole body enters context the moment the skill is judged
  relevant.
- **references linked from SKILL.md** -- a bundled file nothing points at is never read.
- **references one level deep** -- a reference reached from another reference gets partially read
  (`head -100`), which yields incomplete information that looks complete.
- **forward slashes** -- a backslash path breaks on Unix and makes the release-history key differ
  between platforms.
"""

from __future__ import annotations

import re

import pytest

from vqapr.agent.skillset import shipped_skills

MAX_BODY_LINES = 500
MAX_DESCRIPTION = 1024
"""The Anthropic API's `description` limit. Claude Code truncates at 1,536 and Codex shortens
descriptions first when the listing is tight, so the smallest of the three is the one to hold."""

SKILLS = shipped_skills()
NAMES = sorted(SKILLS)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_LINK = re.compile(r"\]\((?!https?:)([^)]+)\)")

WHEN = ("use when", "use for", "use this")
"""Openings that introduce the trigger half of a description.

Matched case-insensitively on the description text. Anthropic's own examples all use "Use when",
and requiring one of these is what makes "says when" checkable rather than a matter of taste.
"""


def _frontmatter(name: str) -> dict[str, str]:
    text = SKILLS[name]["SKILL.md"].decode("utf-8")
    match = _FRONTMATTER.match(text)
    assert match, f"{name}/SKILL.md has no YAML frontmatter"
    fields: dict[str, str] = {}
    key = None
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        elif key:
            fields[key] += " " + line.strip()
    return fields


def test_the_set_is_not_empty() -> None:
    assert NAMES, "the package ships no skills at all"


@pytest.mark.parametrize("name", NAMES)
def test_the_name_matches_the_directory(name: str) -> None:
    """The directory name is what `vqapr skill install` writes and what the release table keys."""
    declared = _frontmatter(name).get("name")
    assert declared == name, f"{name}/SKILL.md declares name: {declared!r}"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", name), name
    for reserved in ("anthropic", "claude"):
        assert reserved not in name, f"{name} uses a reserved word"


@pytest.mark.parametrize("name", NAMES)
def test_the_description_says_what_and_when(name: str) -> None:
    description = _frontmatter(name).get("description", "")
    assert description, f"{name} has an empty description"
    assert len(description) <= MAX_DESCRIPTION, f"{name}: {len(description)} chars"
    assert any(opening in description.lower() for opening in WHEN), (
        f"{name}'s description never says WHEN to use it -- only the name and description are "
        f"preloaded, so it will not be found: {description!r}"
    )
    for person in ("i can ", "i will ", "you can use this"):
        assert person not in description.lower(), (
            f"{name}'s description is not third person; it is injected into the system prompt "
            "and a mixed point of view breaks discovery"
        )


@pytest.mark.parametrize("name", NAMES)
def test_the_body_is_short_enough_to_load(name: str) -> None:
    """No exemptions.

    `introduce-vqapr` was exempt with `xfail(strict=True)` while it held the pre-split body --
    every rung and every status section -- because deleting content before its new home existed
    would have left a window where it was in neither place. Cutting it made this test fail for
    *passing*, which is what the strict marker was for, and the exemption came out with it.
    """
    lines = SKILLS[name]["SKILL.md"].decode("utf-8").count("\n")
    assert lines < MAX_BODY_LINES, (
        f"{name}/SKILL.md is {lines} lines; split it into references/ (PRD §11.2)"
    )


@pytest.mark.parametrize("name", NAMES)
def test_every_bundled_file_is_reachable(name: str) -> None:
    """A reference nothing links to is a file that is never read."""
    body = SKILLS[name]["SKILL.md"].decode("utf-8")
    for path in SKILLS[name]:
        if path == "SKILL.md" or path.startswith("scripts/"):
            continue
        assert path in body, f"{name} ships {path} and its SKILL.md never points at it"


@pytest.mark.parametrize("name", NAMES)
def test_a_script_is_named_by_the_skill_that_ships_it(name: str) -> None:
    """Not linked -- executed. The instruction must still say it exists, by filename."""
    body = SKILLS[name]["SKILL.md"].decode("utf-8")
    for path in SKILLS[name]:
        if not path.startswith("scripts/"):
            continue
        assert path.rsplit("/", 1)[-1] in body, f"{name} ships {path} and never mentions it"


@pytest.mark.parametrize("name", NAMES)
def test_nothing_is_reachable_only_by_a_second_hop(name: str) -> None:
    """Every reference links directly from SKILL.md, whatever else also links it.

    The rule is that a file must not be reachable *only* through another reference, because a
    file arrived at on a second hop gets previewed (`head -100`) rather than read, and partial
    information looks complete. A sibling cross-link to a file SKILL.md already offers is not that
    failure -- it is a pointer to something the reader can, and will, open in full.

    Written this way after the stricter form -- no sibling links at all -- flagged
    `discouraged-preparation.md` pointing at `point-in-time.md`, which SKILL.md offers directly.
    That is a cross-reference, not a hidden file.
    """
    body = SKILLS[name]["SKILL.md"].decode("utf-8")
    for path, content in SKILLS[name].items():
        if not path.startswith("references/"):
            continue
        for link in _LINK.findall(content.decode("utf-8")):
            target = link.split("#", 1)[0].lstrip("./")
            if not target.endswith(".md"):
                continue
            sibling = f"references/{target}"
            if sibling not in SKILLS[name]:
                continue
            assert sibling in body, (
                f"{name}/{path} links to {target}, which SKILL.md does not offer -- so it is "
                "reachable only on a second hop, where it gets previewed rather than read"
            )


@pytest.mark.parametrize("name", NAMES)
def test_the_shipped_bytes_do_not_depend_on_the_build_platform(name: str) -> None:
    """No CR anywhere in a shipped skill file.

    The release history judges an installed file by its sha256 (PRD §11.3). This repository is
    developed with `core.autocrlf=true`, which stores LF and checks out CRLF -- so without
    `.gitattributes` forcing `eol=lf` on `agent/skills/**`, a wheel built on Windows and one built
    on Linux ship different bytes for the same commit, every recorded hash is true on one platform
    and wrong on the other, and a user who touched nothing is told their skills were edited.

    Found by this file: the frontmatter regex would not match, because the line ending was CRLF.
    """
    for path, content in SKILLS[name].items():
        assert b"\r" not in content, (
            f"{name}/{path} carries CR bytes; `.gitattributes` should be forcing eol=lf here, "
            "and without it the release hashes stop crossing platforms"
        )


@pytest.mark.parametrize("name", NAMES)
def test_paths_use_forward_slashes(name: str) -> None:
    for path, content in SKILLS[name].items():
        assert "\\" not in path, path
        if path.endswith(".md"):
            text = content.decode("utf-8")
            assert "references\\" not in text and "scripts\\" not in text, path
