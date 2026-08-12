import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "tests" / "scenarios" / "strategy_capabilities.yaml"
USE_CASE = re.compile(r"^UC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}$")


def _document_ids(path: Path) -> set[str]:
    return set(
        re.findall(
            r"\bUC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}\b",
            path.read_text(encoding="utf-8"),
        )
    )


def test_historical_strategy_capabilities_are_scenarios_not_qlib_oracles() -> None:
    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    authority = payload["authority"]

    assert payload["schema_version"] == 1
    assert authority == {
        "product_requirements": "docs/qlibx-prd.md",
        "implementation_design": "docs/qlibx-architecture.md",
        "reference_mode": "scenario_requirement_source",
        "qlib_numeric_or_api_parity": False,
    }
    assert all((ROOT / path).is_file() for path in payload["reference_sources"])

    prd_ids = _document_ids(ROOT / authority["product_requirements"])
    architecture_ids = _document_ids(ROOT / authority["implementation_design"])
    capabilities = payload["capabilities"]
    capability_by_id = {item["id"]: item for item in capabilities}
    assert len(capability_by_id) == len(capabilities)
    assert {item["status"] for item in capabilities} == {
        "current_supported",
        "future_product_scope",
    }

    for capability in capabilities:
        for use_case in capability["prd_use_cases"]:
            assert USE_CASE.fullmatch(use_case)
            assert use_case in prd_ids
            assert use_case in architecture_ids
        if capability["status"] == "engine_gap":
            assert capability["target_milestone"] in {"M12", "M13"}
        if capability["status"] == "future_product_scope":
            assert capability["prd_use_cases"] == []

    strategies = payload["strategy_scenarios"]
    assert len(strategies) == 18
    assert len({item["name"] for item in strategies}) == 18
    assert {item["family"] for item in strategies} == {
        "market",
        "financial",
        "consensus",
    }
    for strategy in strategies:
        assert strategy["capabilities"]
        assert set(strategy["capabilities"]) <= set(capability_by_id)

    for scenario in payload["runtime_scenarios"]:
        assert set(scenario["required_capabilities"]) <= set(capability_by_id)

    current_runtime = next(
        item
        for item in payload["runtime_scenarios"]
        if item.get("disposition") == "current_supported"
    )
    test_path, test_name = current_runtime["test"].split("::", maxsplit=1)
    assert (ROOT / test_path).is_file()
    assert test_name in (ROOT / test_path).read_text(encoding="utf-8")

    future = {
        item["name"]: item["disposition"]
        for item in payload["runtime_scenarios"]
        if item.get("disposition") == "future_product_scope"
    }
    assert future == {
        "signed_peer_momentum": "future_product_scope",
        "volume_limited_execution": "future_product_scope",
    }