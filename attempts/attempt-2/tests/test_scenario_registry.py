import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "tests" / "scenarios" / "current_scope.yaml"
CONTRACT_REGISTRY = ROOT / "tests" / "scenarios" / "current_contracts.yaml"
FUTURE_REGISTRY = ROOT / "tests" / "scenarios" / "future_characterization.yaml"
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
    assert payload["support_status"] == "current"
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
        assert scenario["inputs"]["data_kind"] == "real"
        assert scenario["expected"]

        test_path_text, function_name = scenario["test"].split("::", maxsplit=1)
        test_path = ROOT / test_path_text
        assert test_path.is_file(), scenario["test"]
        assert function_name in _test_functions(test_path), scenario["test"]
        normalized_id = scenario_id.lower().replace("-", "_")
        assert normalized_id in function_name

        sources = scenario["inputs"].get("sources", [])
        assert sources
        assert all((ROOT / source).is_file() for source in sources)


def test_current_support_ids_are_complete_across_real_and_contract_registries() -> None:
    current = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    contracts = yaml.safe_load(CONTRACT_REGISTRY.read_text(encoding="utf-8"))
    assert current["companion_registries"] == [
        "tests/scenarios/current_contracts.yaml",
        # Interrupted-run recovery has no current companion registry.
    ]
    assert contracts["schema_version"] == 1
    assert contracts["support_status"] == "current"
    assert contracts["fixture_policy"] == "deterministic_contract"

    required = current["required_current_use_cases"]
    assert len(required) == len(set(required))
    assert all(USE_CASE.fullmatch(item) and item.startswith("UC-") for item in required)
    real_scenarios = current["scenarios"]
    contract_scenarios = contracts["scenarios"]
    real_identities = {(item["id"], item["case"]) for item in real_scenarios}
    contract_identities = {(item["id"], item["case"]) for item in contract_scenarios}
    assert len(contract_identities) == len(contract_scenarios)
    assert real_identities.isdisjoint(contract_identities)
    observed_current_ids = {
        item["id"]
        for item in (*real_scenarios, *contract_scenarios)
        if item["id"].startswith("UC-")
    }
    assert observed_current_ids == set(required)

    prd_ids = _document_ids(ROOT / "docs" / "qlibx-prd.md")
    architecture_ids = _document_ids(ROOT / "docs" / "qlibx-architecture.md")
    excluded_gaps = current["excluded_readiness_gaps"]
    assert len({item["id"] for item in excluded_gaps}) == len(excluded_gaps)
    for gap in excluded_gaps:
        assert gap["id"] in prd_ids
        assert gap["id"] in architecture_ids
        assert gap["excludes_current_use_case"] not in required
        assert gap["excludes_current_use_case"] not in observed_current_ids
        assert gap["reason"]
        assert gap["closure_oracle"]

    for scenario in contract_scenarios:
        scenario_id = scenario["id"]
        assert scenario_id in prd_ids
        assert scenario_id in architecture_ids
        assert scenario["inputs"]["fixture_kind"] == "deterministic_contract"
        assert scenario["inputs"]["reason"]
        assert scenario["inputs"]["oracle"]
        assert scenario["expected"]

        test_path_text, function_name = scenario["test"].split("::", maxsplit=1)
        test_path = ROOT / test_path_text
        assert test_path.is_file(), scenario["test"]
        assert function_name in _test_functions(test_path), scenario["test"]
        assert scenario_id.lower().replace("-", "_") in function_name


def test_future_characterization_registry_is_separate_and_executable() -> None:
    current = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    contracts = yaml.safe_load(CONTRACT_REGISTRY.read_text(encoding="utf-8"))
    future = yaml.safe_load(FUTURE_REGISTRY.read_text(encoding="utf-8"))
    assert future["schema_version"] == 1
    assert future["support_status"] == "future_characterization"

    current_identities = {
        (item["id"], item["case"])
        for item in (*current["scenarios"], *contracts["scenarios"])
    }
    future_identities = {(item["id"], item["case"]) for item in future["scenarios"]}
    assert len(future_identities) == len(future["scenarios"])
    assert current_identities.isdisjoint(future_identities)

    prd_ids = _document_ids(ROOT / "docs" / "qlibx-prd.md")
    architecture_ids = _document_ids(ROOT / "docs" / "qlibx-architecture.md")
    for scenario in future["scenarios"]:
        scenario_id = scenario["id"]
        assert USE_CASE.fullmatch(scenario_id)
        assert scenario_id in prd_ids
        assert scenario_id in architecture_ids
        assert scenario["inputs"]["data_kind"] == "synthetic_characterization"
        assert scenario["inputs"]["generator"]
        assert (ROOT / scenario["inputs"]["real_parent_source"]).is_file()
        assert scenario["expected"]["current_support"] is False

        test_path_text, function_name = scenario["test"].split("::", maxsplit=1)
        test_path = ROOT / test_path_text
        assert test_path.is_file(), scenario["test"]
        assert function_name in _test_functions(test_path), scenario["test"]
        assert scenario_id.lower().replace("-", "_") in function_name
