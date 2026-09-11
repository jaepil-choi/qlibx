"""The CLI reads the package through its surfaces: `vqapr.public` and the application layer.

Owner ruling 2026-09-11 (concept-tree campaign, AC4): `cli/` imports `vqapr.public`, the application
layer -- `workspace`, `run`, `record`, `report`, `agent` -- and `domain.errors`, and nothing else. A
verb that reaches into `domain`, `data` or `component` directly is a verb an author cannot reproduce
from the surface they are handed, and the next refactor of those internals breaks the CLI first.
Record `277` moved the last four reaches behind a door: `workspace.registry.load_registered`,
`run.roster.read_roster_tables`, `workspace.preview.preview_dataset` and `agent/scaffold.py`.

An AST walk, function-local imports included: the CLI defers imports for start-up time, and a check
that read only module headers would call those files clean.
"""

from __future__ import annotations

import ast
import pathlib

CLI = pathlib.Path(__file__).parents[2] / "src" / "vqapr" / "cli"

ALLOWED = (
    "vqapr.public",
    "vqapr.workspace",
    "vqapr.run",
    "vqapr.record",
    "vqapr.report",
    "vqapr.agent",
    "vqapr.domain.errors",
    "vqapr.cli",
)


def _allowed(module: str) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in ALLOWED)


def _reaches() -> list[str]:
    found: list[str] = []
    for path in sorted(CLI.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                module = node.module or ""
                if not module.startswith("vqapr"):
                    continue
                modules = [f"vqapr.{a.name}" for a in node.names] if module == "vqapr" else [module]
            elif isinstance(node, ast.Import):
                modules = [a.name for a in node.names if a.name.startswith("vqapr")]
            else:
                continue
            found += [f"{path.name}:{node.lineno} -> {m}" for m in modules if not _allowed(m)]
    return found


def test_the_cli_imports_only_the_surfaces() -> None:
    reached = _reaches()
    assert not reached, (
        "these CLI imports reach past the surfaces:\n  "
        + "\n  ".join(reached)
        + "\n\nImport the name from `vqapr.public`, or from the application-layer module that owns "
        "the service. If neither has it, the service belongs in one of them, not in the CLI."
    )
