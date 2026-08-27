"""A refusal's `fix` must say what to DO, not repeat what was required.

This is the whole premise of the refusal envelope, and it is the one part of it that no type can
enforce. `Failure` already refuses an empty `fix`, but nothing stops a `fix` that paraphrases its
own `requirement` with the verb swapped -- and that construction validates, serializes and ships
looking exactly like guidance.

The risk is concrete rather than theoretical: the 49 call sites were migrated by four independent
authors, and "restate the requirement in the imperative" is the single most natural way for each
of them to have satisfied a required field without adding anything. An architect review found two
such sites; this test is what stops the third from arriving unnoticed.

It works on the source rather than at runtime because most of these refusals need a real failing
workspace to construct. The strings are literals or f-strings in the AST, so they can be compared
without provoking the failure each one describes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "vqapr"

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "the", "be", "must", "is", "are", "was", "were", "to", "of", "in",
        "on", "at", "it", "its", "that", "this", "with", "for", "or", "not", "no", "so",
        "has", "have", "had", "than", "then", "one", "every", "each", "any", "all",
    }
)


def _text(node: ast.expr | None) -> str | None:
    """The comparable text of a string argument, with interpolations reduced to placeholders.

    An f-string's literal segments are what carry its meaning; the interpolated values are the
    same in both fields whenever a `fix` was written by copying its `requirement`, so collapsing
    them is what makes the comparison see the copy.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append(" {} ")
        return "".join(parts)
    return None


def _stem(word: str) -> str:
    """Crude suffix stripping, so `declared` and `declare` are not counted as different words.

    Without it a paraphrase passes on inflection alone: a `fix` that swaps `must be declared` for
    `declare it` contributes `declare` as apparently-new vocabulary while saying exactly what the
    requirement already said. That is the specific evasion this test exists to catch, so the
    comparison has to be blind to word form.
    """
    for suffix in ("ing", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            # `declared` -> `declar` and `declare` -> `declar` only if the trailing `e` is also
            # stripped, so keep going rather than returning on the first match.
            return _stem(word)
    return word


def _significant(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z_]+", text.lower())
    return frozenset(
        _stem(word) for word in words if word not in _STOPWORDS and len(word) > 2
    )


def _sites() -> list[tuple[str, int, str, str]]:
    """Every refusal that supplies both a comparable `requirement` and a comparable `fix`."""
    found: list[tuple[str, int, str, str]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in {"bounded", "Failure"}:
                continue

            keywords = {kw.arg: kw.value for kw in node.keywords}
            requirement = keywords.get("requirement")
            if requirement is None and len(node.args) >= 2:
                requirement = node.args[1]
            fix = keywords.get("fix")

            requirement_text = _text(requirement)
            fix_text = _text(fix)
            if requirement_text and fix_text:
                relative = str(path.relative_to(PACKAGE.parents[1])).replace("\\", "/")
                found.append((relative, node.lineno, requirement_text, fix_text))
    return found


def test_the_sweep_actually_reaches_the_call_sites() -> None:
    """A sweep that silently matched nothing would make every assertion below vacuous."""
    sites = _sites()
    assert len(sites) >= 30, f"only {len(sites)} comparable refusal sites found; the sweep is wrong"


@pytest.mark.parametrize("site", _sites(), ids=lambda s: f"{s[0]}:{s[1]}")
def test_a_fix_is_not_its_requirement_restated(site: tuple[str, int, str, str]) -> None:
    """`fix` must add something the reader did not already have from `requirement`."""
    path, line, requirement, fix = site

    assert fix.strip() != requirement.strip(), (
        f"{path}:{line} repeats its requirement verbatim as its fix"
    )

    requirement_words = _significant(requirement)
    fix_words = _significant(fix)
    assert fix_words, f"{path}:{line} has a fix with no substantive words"

    # The real test: does the fix contribute vocabulary of its own? A pure restatement reuses the
    # requirement's nouns and swaps only the verb, so its new-word set is empty or near-empty.
    contributed = fix_words - requirement_words
    assert contributed, (
        f"{path}:{line} adds no word its requirement did not already use, so it restates rather "
        f"than instructs.\n  requirement: {requirement.strip()!r}\n  fix:         {fix.strip()!r}"
    )
