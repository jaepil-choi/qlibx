"""What the shipped agent skills say, for tests that assert against that prose.

Several tests check that a sentence in the skill still matches the code behind it. They used to
each find the file their own way -- `Path(vqapr.__file__).parent / "agent" / "skill" / "SKILL.md"`
in one, a repo-relative `Path("src/vqapr/agent/skill/SKILL.md")` in another -- and PRD §11.2 turning
the skill into a set broke every one of them separately.

The prose is now read through one helper, and as a **whole**: a sentence is a promise wherever it
is installed, so a claim that moved from `SKILL.md` into a `references/` file has not been retired.
Asserting against one named file would let it survive the move.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.agent.skillset import shipped_skills

MARKDOWN = ".md"


def shipped_prose() -> str:
    """Every markdown byte this package ships as skill content, as one string."""
    return "\n".join(
        content.decode("utf-8")
        for _, files in sorted(shipped_skills().items())
        for path, content in sorted(files.items())
        if path.endswith(MARKDOWN)
    )


def installed_prose(root: Path, target: str = ".agents") -> str:
    """Every markdown byte `vqapr skill install` wrote into *root*, as one string.

    Reads the tree rather than the package when the assertion is about what a reader of the
    installed copy is told -- which is the same bytes, and the test says so by reading the copy.
    """
    base = root / target / "skills"
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(base.rglob(f"*{MARKDOWN}"))
        if path.is_file()
    )
