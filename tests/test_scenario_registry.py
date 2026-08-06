import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "tests" / "scenarios" / "current_scope.yaml"
USE_CASE = re.compile(r"^(?:UC|GAP)-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}$")


def _document_ids(path: Path) -> set[str]:
    return set(
        re.findall(
            r"\b(?:UC|GAP)-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}\b",
            path.read_text(encoding="utf-8"),
        )
    )


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_current_scope_scenario_registry_is_executable_and_self_describing() -> None:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    scenarios = payload["scenarios"]
    identities = {(item["id"], item["case"]) for item in scenarios}
    assert len(identities) == len(scenarios)
    registered_ids = {item["id"] for item in scenarios}
    for coverage_name, required_ids in payload["coverage_sets"].items():
        assert set(required_ids) <= registered_ids, coverage_name

    prd_ids = _document_ids(ROOT / "docs" / "qlibx-prd.md")
    architecture_ids = _document_ids(ROOT / "docs" / "qlibx-architecture.md")
    for scenario in scenarios:
        scenario_id = scenario["id"]
        assert USE_CASE.fullmatch(scenario_id)
        assert scenario_id in prd_ids
        if scenario_id.startswith("UC-"):
            assert scenario_id in architecture_ids
        assert scenario["inputs"]["data_kind"] in {"real", "synthetic_characterization"}
        assert scenario["expected"]

        test_path_text, function_name = scenario["test"].split("::", maxsplit=1)
        test_path = ROOT / test_path_text
        assert test_path.is_file(), scenario["test"]
        assert function_name in _test_functions(test_path), scenario["test"]
        normalized_id = scenario_id.lower().replace("-", "_")
        assert normalized_id in function_name

        if scenario["inputs"]["data_kind"] == "real":
            sources = scenario["inputs"].get("sources", [])
            assert sources
            assert all((ROOT / source).is_file() for source in sources)
        else:
            assert scenario["inputs"].get("generator")
            assert (ROOT / scenario["inputs"]["real_parent_source"]).is_file()
