"""Echolon patterns — parse the patterns SKILL.md, expose programmatic access.

Source: ``echolon/native/skills/echolon_api/patterns/SKILL.md`` (package
data, ships in the wheel). The parser handles YAML frontmatter (block
delimited by ``---`` lines) by skipping it before the section walker starts.
"""
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Pattern:
    name: str
    when_to_use: str
    key_idea: str
    files_to_customize: str
    sketch_code: str
    common_errors: str
    raw_markdown: str


_PATTERNS_MD = (
    Path(__file__).resolve().parent.parent
    / "skills" / "echolon_api" / "patterns" / "SKILL.md"
)

# Matches a section header in one of two forms:
#   **Label:**                (block: content on following lines)
#   **Label:** content text   (inline: content on same line)
_SECTION_HEADER = re.compile(r"^\*\*([^*]+):\*\*\s*(.*)$")


def _normalize_key(name: str) -> str:
    """Convert a pattern display name into a lookup key: lowercase, whitespace/hyphens → underscore."""
    return re.sub(r"[\s-]+", "_", name.lower())


def _parse_patterns() -> dict[str, Pattern]:
    """Parse docs/PATTERNS.md into a dict of Pattern objects keyed by name."""
    if not _PATTERNS_MD.is_file():
        return {}
    raw = _PATTERNS_MD.read_text()

    # Patterns are delimited by "## N. Name" or "## Name" headers
    patterns: dict[str, Pattern] = {}
    current_name: str | None = None
    current_sections: dict[str, list[str]] = {}
    current_key: str | None = None

    def flush():
        if current_name is None:
            return
        sections_joined = {k: "\n".join(v).strip() for k, v in current_sections.items()}
        patterns[_normalize_key(current_name)] = Pattern(
            name=current_name,
            when_to_use=sections_joined.get("when to use", ""),
            key_idea=sections_joined.get("key idea", ""),
            files_to_customize=sections_joined.get("files to customize", ""),
            sketch_code=sections_joined.get("sketch", ""),
            common_errors=sections_joined.get("common errors", ""),
            raw_markdown="",  # raw slice omitted for brevity
        )

    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("## Indicator Naming"):
            flush()
            # Trim leading number like "## 1. Trend Breakout" → "Trend Breakout"
            name = stripped[3:].lstrip("0123456789. ")
            current_name = name
            current_sections = {}
            current_key = None
            continue
        if current_name is None:
            continue
        m = _SECTION_HEADER.match(stripped)
        if m:
            current_key = m.group(1).lower()
            inline = m.group(2)
            current_sections[current_key] = [inline] if inline else []
        elif current_key is not None:
            current_sections[current_key].append(line)
    flush()
    return patterns


_CACHE = _parse_patterns()


def list_patterns() -> list[str]:
    return sorted(_CACHE.keys())


def get_pattern(name: str) -> Pattern | None:
    return _CACHE.get(_normalize_key(name))


__all__ = ["Pattern", "list_patterns", "get_pattern"]
