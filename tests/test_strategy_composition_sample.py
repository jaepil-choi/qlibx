import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from qlibx import QlibxProject
from qlibx.config import ChangeAction

SAMPLE_ID = "strategy-composition-v1"


def run_sample(
    script: Path,
    project_root: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, object]:
    completed = runner((script, project_root), check=True, cwd=project_root)
    return json.loads(completed.stdout)


def test_uc_alpha_path_001_installed_composition_preserves_source_lineage(
    tmp_path: Path,
    run_python_subprocess: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    root = tmp_path / "strategy-composition-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample(SAMPLE_ID)
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)
    applied = project.materialize_sample(SAMPLE_ID, apply=True)
    repeated = project.materialize_sample(SAMPLE_ID, apply=True)
    assert applied.applied is repeated.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)

    sample_dir = root / "examples" / "qlibx_owned" / "strategy_composition"
    consumer_source = (sample_dir / "consumer_strategy.py").read_text(
        encoding="utf-8"
    )
    assert "from qlibx import (" in consumer_source
    assert "from qlibx." not in consumer_source

    result = run_sample(sample_dir / "run.py", root, run_python_subprocess)

    assert result["module_path"] == "sample_frozen_ensemble_consumer.py"
    assert result["source_content_hashes_before"] == result[
        "source_content_hashes_after"
    ]
    assert result["producer_calls_before_composition"] == {
        "sample.path-producer-a": 2,
        "sample.path-producer-b": 2,
    }
    assert result["producer_calls_after_downstream"] == result[
        "producer_calls_before_composition"
    ]
    assert result["ensemble_state_identity"] is None

    lineage = result["ensemble_source_state_lineage"]
    assert len(lineage) == 2
    assert {account for item in lineage for account in item["account_ids"]} == {
        "sample-source-account-a",
        "sample-source-account-b",
    }
    assert {
        state["strategy_id"]
        for item in lineage
        for state in item["strategy_state"]
    } == {"sample.path-producer-a", "sample.path-producer-b"}
    source_ids = result["source_artifact_ids"]
    assert [item["source_artifact_id"] for item in lineage] == source_ids

    assert result["downstream_account_id"] == "sample-downstream-account-b"
    assert set(result["downstream_decision_account_ids"]) == {
        "sample-downstream-account-b"
    }
    assert result["downstream_decision_account_versions"][-1] > 0
    assert {
        account_id
        for pair in result["downstream_execution_account_ids"]
        for account_id in pair
    } == {"sample-downstream-account-b"}
    assert set(result["downstream_direct_state_access_counts"]) == {0}
    assert set(result["downstream_direct_strategy_state_access_counts"]) == {0}
    assert all(item == source_ids for item in result["downstream_source_lineage_ids"])
    assert result["final_positions"]
    assert {
        "decision_intent",
        "execution_result",
        "strategy_extension_registration",
        "strategy_result",
    }.issubset(result["artifact_types"])

    installed = root / project.config.extension_dir / result["module_path"]
    installed.write_text(
        installed.read_text(encoding="utf-8") + "\n# user change\n",
        encoding="utf-8",
    )
    refused = run_python_subprocess((sample_dir / "run.py", root), check=False, cwd=root)
    assert refused.returncode != 0
    assert "refusing to overwrite modified" in refused.stderr
