import ast
from pathlib import Path

from qlibx.view import ExecutionView, MaterializeView, MonitorView, StrategyView

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "src" / "qlibx"

LAYER_DEPENDENCIES = {
    "kernel": set(),
    "data": {"domain", "models", "errors"},
    "view": {"kernel", "data", "domain", "models", "errors"},
    "operations": {"view", "data", "domain", "models", "errors"},
    "extensions": {
        "view",
        "data",
        "domain",
        "operations",
        "models",
        "errors",
    },
    "portfolio": {"view", "data", "domain", "models", "errors"},
    "execution": {
        "view",
        "data",
        "portfolio",
        "evidence",
        "domain",
        "models",
        "errors",
    },
    "account": {"domain", "models", "errors"},
    "evidence": {"domain", "models", "errors"},
    "analysis": {"view", "data", "domain", "models", "errors"},
    "production": {"evidence", "domain", "models", "errors"},
    "flow": {
        "kernel",
        "data",
        "view",
        "specs",
        "operations",
        "extensions",
        "portfolio",
        "execution",
        "account",
        "evidence",
        "analysis",
        "production",
        "domain",
        "models",
        "errors",
    },
    "specs": {"execution", "portfolio", "operations", "kernel", "models", "errors"},
    "config": {"models", "errors"},
}


def qlibx_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            if name.startswith("qlibx."):
                imported.add(name.split(".", maxsplit=2)[1])
    return imported


def test_layer_import_direction() -> None:
    violations: list[str] = []
    for layer, allowed in LAYER_DEPENDENCIES.items():
        for path in (SOURCE / layer).rglob("*.py"):
            forbidden = qlibx_imports(path) - allowed - {layer}
            if forbidden:
                violations.append(f"{path.relative_to(ROOT)} imports {sorted(forbidden)}")
    assert not violations, "\n".join(violations)


def test_role_views_expose_only_their_authorized_capabilities() -> None:
    dataset_capabilities = {"as_of", "history", "session", "at", "latest", "accessed"}
    strategy_only_capabilities = {
        "artifact",
        "artifact_accessed",
        "account_feedback",
        "feedback_accessed",
        "latest_session_performance",
        "performance_accessed",
        "memory_snapshot",
        "memory_accessed",
    }
    account_capabilities = {"account_snapshot", "state_accessed"}

    for view_type in (MaterializeView, ExecutionView, MonitorView, StrategyView):
        assert all(hasattr(view_type, capability) for capability in dataset_capabilities)
    for view_type in (MaterializeView, ExecutionView, MonitorView):
        assert not any(
            hasattr(view_type, capability) for capability in strategy_only_capabilities
        )
    for view_type in (MaterializeView, ExecutionView):
        assert not any(hasattr(view_type, capability) for capability in account_capabilities)
    assert all(hasattr(MonitorView, capability) for capability in account_capabilities)
    assert all(hasattr(StrategyView, capability) for capability in account_capabilities)
    assert all(
        hasattr(StrategyView, capability) for capability in strategy_only_capabilities
    )


def test_production_source_does_not_read_wall_clock_directly() -> None:
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "now"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "wall-clock reads must go through Clock: " + ", ".join(violations)
