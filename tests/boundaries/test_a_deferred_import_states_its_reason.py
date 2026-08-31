"""Function-local `vqapr` imports are capped, so this refactoring cannot quietly grow them.

`pyproject.toml` explains why this package declines an import-linter:

> a misplaced type surfaces as a circular import, which Python reports without a tool.

**That premise is already false where it matters most.** A function-local import defers the cycle to
the first call, so Python stops reporting it -- and 111 of them exist. Two thirds sit in
`project.py` and the six `_internal/*_bridge.py` modules, which is the same S1 duplication the
structural audit is about: two definitions of one concept, and a translation layer that can only
avoid a cycle by importing late.

The ceiling is not a claim that deferred imports are wrong. Some are load-bearing, and the ones that
are say so. It is a ratchet: every step from here moves code between modules, and the cheapest wrong
way to fix a resulting circular import is a new function-local import. Without a cap, this
refactoring's own execution is the most likely thing to push the number up.

It is armed BEFORE the first code-moving step for that reason.
"""

from __future__ import annotations

import ast
import pathlib

CEILING = 99
"""Measured at record `115`: 106 in total, less the 7 in `JUSTIFIED` below.

Was 104. Record `115` hoisted five function-local imports out of `flow/roster.py` and
`flow/records.py` that had been deferred inside `vqapr.public`, where the facade sits above
everything; that justification did not travel when the code moved to `flow/`, and
`flow/orchestration.py` already imports `vqapr.workspace` eagerly. Lowering the constant in the
same commit is what this ratchet is for.

This number may go DOWN freely; it may not go up.

Lowering it is the point -- resolving the S1 duplication removes most of these by construction. When
a step lowers the count, it lowers this constant in the same commit, so the ratchet tightens rather
than leaving slack for the next accident to fill.
"""

JUSTIFIED: dict[str, str] = {
    "src/vqapr/_internal/run_bridge.py": (
        "Deliberate, and pinned by a test rather than by intent: "
        "tests/internal/test_run_bridge.py:165 "
        "(test_importing_run_bridge_does_not_pull_flow_or_workspace) asserts that importing this "
        "module does not drag `flow` or `workspace` into sys.modules. The laziness IS the "
        "contract here, so these do not count against the ceiling."
    ),
}
"""Modules whose deferred imports are a stated contract, excluded by name with the reason.

An allowlist by name and not by pattern: a module earns its way onto this list by having a test
that would fail if the import were hoisted, and the entry cites that test. Everything else counts.
"""


def _deferred_imports() -> dict[str, int]:
    """Function-local `from vqapr ...` / `import vqapr...` statements, per module.

    Walks function bodies rather than the module header, which is the whole point: a module-level
    import is visible to Python's own cycle detection and a function-local one is not.
    """
    counts: dict[str, int] = {}
    for path in sorted(pathlib.Path("src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if inner is node:
                    continue
                from_vqapr = isinstance(inner, ast.ImportFrom) and (
                    inner.module or ""
                ).startswith("vqapr")
                import_vqapr = isinstance(inner, ast.Import) and any(
                    alias.name.startswith("vqapr") for alias in inner.names
                )
                if from_vqapr or import_vqapr:
                    found += 1
        if found:
            counts[path.as_posix()] = found
    return counts


def test_deferred_vqapr_imports_do_not_grow() -> None:
    """The ratchet, with a per-file breakdown so a failure names where it happened."""
    counts = {
        path: found for path, found in _deferred_imports().items() if path not in JUSTIFIED
    }
    total = sum(counts.values())

    breakdown = "\n  ".join(
        f"{found:>3}  {path}"
        for path, found in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    assert total <= CEILING, (
        f"function-local `vqapr` imports rose to {total}, above the ceiling of {CEILING}.\n  "
        + breakdown
        + "\n\nA deferred import hides a circular import from Python, which is the mechanism "
        "`pyproject.toml` relies on instead of an import-linter. If the cycle is real, fix the "
        "cycle; if the laziness is load-bearing, add the module to JUSTIFIED with the test that "
        "proves it."
    )


def test_the_ceiling_is_not_slack() -> None:
    """A ceiling far above the real count stops being a ratchet.

    If a step removes deferred imports, it lowers `CEILING` in the same commit. This fails when the
    constant drifts above reality, which is how a cap silently turns into permission.
    """
    total = sum(
        found for path, found in _deferred_imports().items() if path not in JUSTIFIED
    )

    assert total == CEILING, (
        f"the real count is {total} and the ceiling is {CEILING}. Lower CEILING to {total} in the "
        "commit that removed them, so the next accident has no room to fill."
    )


def test_every_justified_module_cites_the_test_that_proves_it() -> None:
    """An allowlist entry without evidence is an exception, not a justification."""
    for module, reason in JUSTIFIED.items():
        assert pathlib.Path(module).is_file(), f"{module} is allowlisted and does not exist"
        assert "tests/" in reason, (
            f"{module}'s justification must cite the test that fails if the import is hoisted; "
            "otherwise it is an assertion of intent, which is what this file exists to replace"
        )


def test_the_justified_module_actually_defers() -> None:
    """Guard the allowlist against becoming stale in the other direction.

    If `run_bridge` ever stops deferring, its entry is dead weight that would silently absorb a
    future accident.
    """
    counts = _deferred_imports()

    for module in JUSTIFIED:
        assert counts.get(module, 0) > 0, (
            f"{module} is allowlisted for deferred imports and has none; remove the entry rather "
            "than leaving room for an unrelated one to hide in"
        )
