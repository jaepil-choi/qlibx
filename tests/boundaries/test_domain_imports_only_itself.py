"""`domain/` is the bottom of the package: it imports nothing from any other `vqapr` package.

Until one-shape Step 7 (record 162) this file guarded `runtime/` against importing `data/`.
`runtime/agendas.py` is now `domain/agendas.py`, and the guard is the general one: every module
under `domain/` may import `vqapr.domain.*` and the standard library, and nothing else -- so a
value can be handed to a Model, a constraint or an account without dragging a layer along.
"""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parents[2] / "src" / "vqapr" / "domain"


def test_domain_imports_nothing_above_it() -> None:
    violations: list[str] = []
    for module in sorted(DOMAIN_ROOT.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            else:
                continue
            for name in imported:
                if name.startswith("vqapr") and not name.startswith("vqapr.domain"):
                    violations.append(f"{module.name}:{node.lineno} imports {name}")
    assert violations == []
