import ast
from pathlib import Path

RUNTIME_ROOT = Path(__file__).parents[2] / "src" / "vqapr" / "runtime"


def test_runtime_does_not_import_the_data_layer() -> None:
    violations: list[str] = []
    for module in sorted(RUNTIME_ROOT.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            else:
                continue
            if any(name == "vqapr.data" or name.startswith("vqapr.data.") for name in imported):
                violations.append(f"{module.name}:{node.lineno}")

    assert violations == []
