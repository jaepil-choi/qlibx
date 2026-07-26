from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative_path: str):
    path = INTEGRATION_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_find_exact_candidate_requires_one_full_parameter_match() -> None:
    builder = load_script(
        "subset_manifest_builder",
        "research/diagnostics/build_subset_manifests.py",
    )
    candidates = [
        {
            "signal": "low_beta_252",
            "neutralization": "market_beta_projection",
            "rank_power": 1.0,
            "rebalance_interval": 1,
        },
        {
            "signal": "low_beta_252",
            "neutralization": "market_beta_projection",
            "rank_power": 1.0,
            "rebalance_interval": 21,
        },
    ]
    selector = {
        "signal": "low_beta_252",
        "neutralization": "market_beta_projection",
        "rank_power": 1.0,
        "rebalance_interval": 21,
    }

    selected = builder.find_exact_candidate(
        candidates,
        selector,
        fields=(
            "signal",
            "neutralization",
            "rank_power",
            "rebalance_interval",
        ),
    )

    assert selected["rebalance_interval"] == 21


def test_find_exact_candidate_fails_on_ambiguous_match() -> None:
    builder = load_script(
        "subset_manifest_builder_ambiguous",
        "research/diagnostics/build_subset_manifests.py",
    )
    candidates = [{"name": "same"}, {"name": "same"}]

    with pytest.raises(ValueError, match="found 2"):
        builder.find_exact_candidate(
            candidates,
            {"name": "same"},
            fields=("name",),
        )


def test_reused_catalog_run_is_resolved_by_exact_alpha_key() -> None:
    publisher = load_script(
        "alpha_family_challenger_publisher",
        "research/challenger/publish_alpha_family_challengers.py",
    )
    runs = pd.DataFrame(
        {
            "run_id": ["research-a", "research-b"],
            "alpha_key": ["market.alpha_a", "market.alpha_b"],
        }
    ).set_index("run_id")

    assert (
        publisher.resolve_run_id_by_alpha_key(runs, "market.alpha_b")
        == "research-b"
    )


def test_reused_catalog_run_rejects_missing_or_duplicate_key() -> None:
    publisher = load_script(
        "alpha_family_challenger_publisher_errors",
        "research/challenger/publish_alpha_family_challengers.py",
    )
    runs = pd.DataFrame(
        {
            "run_id": ["research-a", "research-b"],
            "alpha_key": ["market.same", "market.same"],
        }
    ).set_index("run_id")

    with pytest.raises(ValueError, match="found 2"):
        publisher.resolve_run_id_by_alpha_key(runs, "market.same")
    with pytest.raises(ValueError, match="found 0"):
        publisher.resolve_run_id_by_alpha_key(runs, "market.missing")


def test_trusted_source_fingerprint_resolves_semantic_keys() -> None:
    publisher = load_script(
        "alpha_family_challenger_fingerprint",
        "research/challenger/publish_alpha_family_challengers.py",
    )
    runs = pd.DataFrame(
        {
            "run_id": ["research-a", "research-b"],
            "alpha_key": ["market.atomic", "market.cohort"],
            "data_fingerprint": ["same-data", "same-data"],
        }
    ).set_index("run_id")
    family_config = {
        "reused_atomics": {"member": "market.atomic"},
        "reused_cohorts": {
            "calendar": {"alpha_key": "market.cohort", "member_names": ["a", "b"]}
        },
    }

    assert (
        publisher.trusted_source_fingerprint(family_config, runs)
        == "same-data"
    )
