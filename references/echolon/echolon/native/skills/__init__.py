"""Echolon skills — programmatic access to in-package skill markdown.

Makes the ``SKILL.md`` packets reachable via MCP for agents connecting
through ``echolon-mcp``, plus to direct skill-runtime consumers (Claude
Code Skill tool, OpenAI Agents SDK skill loader).

The ``Skill`` dataclass + ``list_skills()`` / ``get_skill(name)`` API
mirrors the patterns and templates surfaces; the MCP server wraps these
to expose skills as data, not just files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_SKILLS_ROOT = Path(__file__).parent / "echolon_api"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    body: str               # full SKILL.md text (frontmatter included)
    body_no_frontmatter: str  # body with the YAML frontmatter block stripped


def _parse_frontmatter(body: str) -> tuple[dict[str, str], str]:
    """Return ``(frontmatter_fields, body_without_frontmatter)``.

    Frontmatter is delimited by leading ``---`` lines. Within the block,
    each line is parsed as ``key: value`` (no nested structures). Anything
    after the second ``---`` is the body.
    """
    m = _FRONTMATTER.match(body)
    if not m:
        return {}, body
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body[m.end():]


def list_skills() -> list[str]:
    """Return all known skill names, sorted.

    A directory under ``echolon/native/skills/echolon_api/`` is a skill iff it
    contains a ``SKILL.md`` file. The skill name is the directory name.
    """
    return sorted(
        d.name for d in _SKILLS_ROOT.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    )


def get_skill(name: str) -> Skill | None:
    """Load one skill by name. Returns None if unknown."""
    skill_md = _SKILLS_ROOT / name / "SKILL.md"
    if not skill_md.is_file():
        return None
    body = skill_md.read_text()
    frontmatter, no_fm = _parse_frontmatter(body)
    return Skill(
        name=name,
        description=frontmatter.get("description", ""),
        body=body,
        body_no_frontmatter=no_fm.strip(),
    )


__all__ = ["Skill", "list_skills", "get_skill"]
