import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
RECOVERY_REGISTRY = ROOT / "tests" / "scenarios" / "recovery.yaml"


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_recovery_gap_registry_owns_process_crash_matrix() -> None:
    payload = yaml.safe_load(RECOVERY_REGISTRY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["support_status"] == "current_readiness_gap"
    assert payload["gap_id"] == "GAP-RECOVERY-001"
    assert payload["gap_id"] in (
        ROOT / "docs" / "qlibx-prd.md"
    ).read_text(encoding="utf-8")

    scenario = payload["scenario"]
    assert scenario["inputs"]["data_kind"] == "real"
    assert scenario["inputs"]["fault_kind"] == "process_termination"
    assert len(scenario["inputs"]["crash_points"]) >= 6
    assert all((ROOT / source).is_file() for source in scenario["inputs"]["sources"])
    assert scenario["expected"] == {
        "uninterrupted_parity": True,
        "duplicate_decision": False,
        "duplicate_fill": False,
        "duplicate_memory_commit": False,
        "feedback_cursor_parity": True,
        "artifact_identity_parity": True,
    }

    for node in (scenario["test"], payload["identity_guard"]["test"]):
        test_path_text, function_name = node.split("::", maxsplit=1)
        test_path = ROOT / test_path_text
        assert test_path.is_file(), node
        assert function_name in _test_functions(test_path), node
        assert "gap_recovery_001" in function_name