from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from qlibx import Project, QlibxError
from qlibx.research import (
    AlphaDescriptor,
    ResearchCatalog,
    ResearchProposal,
    compare_alpha,
)


def _proposal(*, mechanism: str = "reversal") -> ResearchProposal:
    return ResearchProposal(
        hypothesis=f"test {mechanism}",
        mechanism=mechanism,
        logical_datasets=("returns",),
        observation_clock="t-1 close",
        holding_horizon="5d",
        strategy="rolling_reversal",
        transforms=("rank",),
        parameter_range={"window": [3, 5, 10]},
        evaluation_segment={"start": "2025-01-01", "end": "2025-03-31"},
        comparison_set=("baseline",),
        cost_assumptions={"bps": 10},
        capacity_assumptions={"participation": 0.1},
        stopping_condition="three failures",
        search_limit=3,
    )


def _publish_alpha(catalog: ResearchCatalog, session: str, value: float) -> str:
    attempt = catalog.begin(
        session_id=session,
        invocation={"session": session, "value": value},
        kind="alpha_run",
    )
    catalog.stage_frame(attempt, "weights", pd.DataFrame({"A": [value]}))
    published = catalog.publish(
        attempt,
        status="successful",
        metadata={
            "descriptor": {
                "mechanism": "reversal",
                "inputs": ["returns"],
                "clock": "t-1 close",
            }
        },
    )
    return published.record_id


def test_frozen_bundle_survives_later_config_edit_and_records_inputs(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    catalog = ResearchCatalog.from_project(project)
    assert catalog.state == project.paths.research
    config = tmp_path / "config" / "qlibx" / "trial.yaml"
    config.write_text("window: 5\n", encoding="utf-8")
    original_bytes = config.read_bytes()
    bundle = catalog.freeze_run(
        session_id="session-a",
        config_files={"trial": config},
        dataset_snapshots={"returns": "sha256:returns-v1"},
        component_versions={"strategy": "reversal:3", "qlib": "0.9.7"},
        seed=19,
    )
    config.write_text("window: 99\n", encoding="utf-8")
    loaded = catalog.load_frozen_run(bundle.bundle_id)
    assert loaded["configs"]["trial"]["content"].encode("utf-8") == original_bytes
    assert loaded["dataset_snapshots"]["returns"] == "sha256:returns-v1"
    assert loaded["component_versions"]["qlib"] == "0.9.7"
    assert loaded["seed"] == 19


def test_incomplete_prepare_is_hidden_and_recovered_by_new_catalog(tmp_path: Path) -> None:
    project = Project.initialize(tmp_path)
    catalog = ResearchCatalog.from_project(project)
    attempt = catalog.begin(session_id="crashed", invocation={"x": 1}, kind="alpha_run")
    catalog.stage_json(attempt, "result", {"value": 1})
    plan = catalog.prepare_publication(attempt, status="successful", metadata={})
    assert catalog.list_results() == ()
    assert catalog.list_incomplete_attempts()[0]["status"] == "incomplete"

    recovered_catalog = ResearchCatalog.from_project(Project.load(tmp_path))
    outcome = recovered_catalog.recover_publications()
    assert {item["status"] for item in outcome} == {"recovered"}
    assert recovered_catalog.list_results()[0]["record_id"] == plan.manifest["record_id"]
    assert recovered_catalog.list_incomplete_attempts() == ()


def test_installed_but_uncommitted_record_is_hidden_then_recovered(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    attempt = catalog.begin(session_id="crashed", invocation={"x": 2}, kind="alpha_run")
    catalog.stage_json(attempt, "result", {"value": 2})
    plan = catalog.prepare_publication(attempt, status="successful", metadata={})
    catalog.install_publication(plan)
    assert catalog.list_results() == ()
    assert ResearchCatalog(catalog.state).recover_publications()[0]["status"] == "recovered"
    assert len(catalog.list_results()) == 1


def test_status_context_proposal_nearest_range_and_stale_decision(tmp_path: Path) -> None:
    catalog = ResearchCatalog.from_project(Project.initialize(tmp_path))
    proposal = catalog.create_proposal(_proposal(), session_id="a", agent_id="agent-a")
    catalog.create_proposal(_proposal(mechanism="quality"), session_id="b", agent_id="agent-b")
    record_id = _publish_alpha(catalog, "a", 0.2)
    failed = catalog.begin(session_id="b", invocation={"x": "failed"}, kind="alpha_run")
    catalog.stage_json(failed, "error", {"reason": "no coverage"})
    catalog.publish(failed, status="failed", metadata={"searched": {"window": 30}})
    invalid = catalog.begin(session_id="c", invocation={"x": "invalid"}, kind="alpha_run")
    catalog.stage_json(invalid, "error", {"reason": "axis mismatch"})
    catalog.publish(invalid, status="invalid", metadata={})
    catalog.begin(session_id="d", invocation={"x": "crashed"}, kind="alpha_run")

    context = catalog.query_context(
        candidate={"mechanism": "reversal", "inputs": ["returns"], "clock": "t-1 close"},
        required_comparison_set=("baseline",),
        research_gaps=("sector exposure",),
    )
    assert {item["status"] for item in context.prior_results} == {
        "successful",
        "failed",
        "invalid",
    }
    assert context.incomplete_attempts[0]["status"] == "incomplete"
    assert {3, 5, 10} <= set(context.searched_parameter_ranges[0]["window"])
    assert context.nearest_neighbors[0]["record_id"] == record_id
    assert context.required_comparison_set == ("baseline",)
    assert context.research_gaps == ("sector exposure",)

    decision = catalog.record_decision(
        proposal.proposal_id,
        decision="promote",
        evidence_run_ids=(record_id,),
        criteria={"ir": "> 0"},
        reviewer="reviewer-a",
        rationale="bounded evidence passed",
        expected_version=0,
    )
    assert decision.version == 1
    with pytest.raises(QlibxError) as stale:
        catalog.record_decision(
            proposal.proposal_id,
            decision="reject",
            evidence_run_ids=(record_id,),
            criteria={},
            reviewer="reviewer-b",
            rationale="stale",
            expected_version=0,
        )
    assert stale.value.code == "CONFLICT"
    assert stale.value.context["current_version"] == 1
    assert stale.value.context["expected_version"] == 0


def test_three_independent_processes_publish_on_one_project(tmp_path: Path) -> None:
    Project.initialize(tmp_path)
    program = """
import sys
import pandas as pd
from qlibx import Project
from qlibx.research import ResearchCatalog
root, session, value = sys.argv[1], sys.argv[2], float(sys.argv[3])
catalog = ResearchCatalog.from_project(Project.load(root))
attempt = catalog.begin(session_id=session, invocation={'session': session}, kind='alpha_run')
catalog.stage_frame(attempt, 'weights', pd.DataFrame({'A': [value]}))
result = catalog.publish(attempt, status='successful', metadata={'session': session})
print(result.record_id)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(tmp_path), f"agent-{index}", str(index)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(3)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        outputs.append(stdout.strip())
    assert len(set(outputs)) == 3
    catalog = ResearchCatalog.from_project(Project.load(tmp_path))
    assert len(catalog.list_results()) == 3


def test_orthogonality_records_three_levels_segment_pool_metrics_and_thresholds() -> None:
    candidate = AlphaDescriptor(
        "candidate",
        "reversal",
        ("returns",),
        "t-1 close",
        "5d",
        ("rank",),
    )
    reference = AlphaDescriptor(
        "reference",
        "reversal",
        ("returns",),
        "t-1 close",
        "10d",
        ("zscore",),
    )
    dates = pd.date_range("2025-01-01", periods=3)
    left = pd.DataFrame({"A": [1.0, -1.0, 2.0]}, index=dates)
    right = pd.DataFrame({"A": [1.0, 1.0, -1.0]}, index=dates)
    result = compare_alpha(
        candidate,
        reference,
        candidate_signal=left,
        reference_signal=right,
        empirical_pairs={"return": (left * 0.01, right * 0.01)},
        incremental_metrics={"cost_aware_marginal_ir": 0.4, "capacity": 1_000_000.0},
        reference_pool=("reference", "benchmark"),
        evaluation_segment={"start": "2025-01-01", "end": "2025-01-03"},
        thresholds={"residual_ratio": 0.2, "cost_aware_marginal_ir": 0.1},
    )
    assert result.classification == "family_variation"
    assert result.reference_pool == ("reference", "benchmark")
    assert result.evaluation_segment["start"] == "2025-01-01"
    assert "return_correlation" in result.empirical_metrics
    assert result.incremental_metrics["cost_aware_marginal_ir"] == pytest.approx(0.4)
    assert result.threshold_outcomes["cost_aware_marginal_ir"] is True
    assert json.loads(json.dumps(result.thresholds))["residual_ratio"] == pytest.approx(0.2)
