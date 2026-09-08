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

CEILING = 10  # record `191`: `exchange/execution_table.py`'s two guards, hoisted
"""Was 12 after record `186` (the lazy roster import in `exchange/listings.py` moved to the top).
Record `191` (layering campaign M2) hoisted the two `accepted_requests` guards in
`exchange/execution_table.py`: they deferred `account.snapshot` and `orders.batches` because
`exchange` importing either at module level was a cycle, and both types are now
`domain/account_state.py` and `domain/orders.py`. The cycle is gone rather than deferred.

Measured at record `126`: 37 in total, with `JUSTIFIED` now empty.
Was 18 after record `149`. Record `162` (one-shape Step 7) removed `data/store.py`'s
`_window_types` and the two `ExecutionTable` guards in `exchange/conventions.py`:
each deferred an import that was a cycle, and the cycle is gone rather than deferred.
Then 15 -> 13 in the same record: `domain/roster.py` and `roster_export.py` folded into
`domain/instruments.py`, so the two deferred `build_roster`/`read_roster_table` pairs in
`cli/list_.py` and `declarations.py` became one statement each. The deferrals stayed; the count
is statements.

Was 23 after record `132`. Record `134` removed the function-local `Workspace` import in
`declarations._instruments`: the roster is staged on the transaction `_apply` already holds.

Was 35 after record `131`. Record `132` deleted `_internal/strategy_bridge.py` and
`_internal/models/agent_first.py` -- the adapter between the two StrategyModel classes -- and
the two deferred imports `extension/loading.py` needed to reach them; the bridge itself carried
the rest.

Was 41 after record `125`, 44 after record `124`, and 99 before that. Record `126` merged the
two lookback pairs into one class each, which deleted `engine_lookback` and the four deferred
imports it needed to name both sides of a translation that no longer exists.

Before that: Record `124` deleted `project.py`, five `_internal`
bridges and `extension/identity.py`, which between them held most of the deferred imports this
ratchet was counting — `project.py` alone deferred nearly all of its own. Record `125` took three
more out of `strategy_bridge`, which stopped importing `vqapr.public` at all once the Flow took
over stamping the intent. Lowering the constant in the same commit is what this ratchet is for.

Was 104 before that. Record `115` hoisted five function-local imports out of `flow/roster.py` and
`flow/records.py` that had been deferred inside `vqapr.public`, where the facade sits above
everything; that justification did not travel when the code moved to `flow/`, and
`flow/orchestration.py` already imports `vqapr.workspace` (now `vqapr.project.store`) eagerly.

This number may go DOWN freely; it may not go up.

Lowering it is the point -- resolving the S1 duplication removes most of these by construction. When
a step lowers the count, it lowers this constant in the same commit, so the ratchet tightens rather
than leaving slack for the next accident to fill.
"""

JUSTIFIED: dict[str, str] = {}
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
