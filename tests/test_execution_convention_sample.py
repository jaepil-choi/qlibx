import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from qlibx import QlibxProject
from qlibx.config import ChangeAction

SAMPLE_ID = "execution-convention-comparison-v1"


def test_installed_execution_convention_sample_reuses_one_frozen_parent(
    tmp_path: Path,
    run_python_subprocess: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    root = tmp_path / "execution-convention-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample(SAMPLE_ID)
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)
    applied = project.materialize_sample(SAMPLE_ID, apply=True)
    repeated = project.materialize_sample(SAMPLE_ID, apply=True)
    assert applied.applied is repeated.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)

    sample_dir = (
        root / "examples" / "qlibx_owned" / "execution_convention_comparison"
    )
    completed = run_python_subprocess(
        (sample_dir / "run.py", root),
        check=True,
        cwd=root,
    )
    result = json.loads(completed.stdout)

    assert result["parent_content_hash_before"] == result["parent_content_hash_after"]
    assert result["producer_calls_before_children"] == 1
    assert result["producer_calls_after_children"] == 1
    parent_id = result["parent_artifact_id"]

    close_child = result["close_child"]
    assert close_child["profile_id"] == "daily.next-session-close.v1"
    assert close_child["convention_id"] == "close-price.v1"
    assert close_child["event_time"] == "2024-01-03T06:30:00+00:00"
    assert close_child["price_role"] == "close_execution_price"
    assert close_child["price"] == 125
    assert close_child["quantity"] == 80
    assert close_child["account_before"] == close_child["account_after"] == (
        "sample-next-close-account"
    )
    assert close_child["decision_dependency_ids"] == [parent_id]
    assert close_child["dataset_dependency_roles"] == ["close_execution_price"]

    open_child = result["open_child"]
    assert open_child["profile_id"] == "daily.next-session-open.v1"
    assert open_child["convention_id"] == "open-price.v1"
    assert open_child["event_time"] == "2024-01-03T00:00:00+00:00"
    assert open_child["price_role"] == "open_execution_price"
    assert open_child["price"] == 120
    assert open_child["quantity"] == 83
    assert open_child["account_before"] == open_child["account_after"] == (
        "sample-next-open-account"
    )
    assert open_child["decision_dependency_ids"] == [parent_id]
    assert open_child["dataset_dependency_roles"] == ["open_execution_price"]

    assert close_child["strategy_result_count"] == open_child["strategy_result_count"] == 0
    assert close_child["memory_commit_count"] == open_child["memory_commit_count"] == 0
    assert result["future_hidden_failure_code"] == "EXECUTION_SESSION_PRICE_MISSING"
    assert result["future_hidden_commit_status"] == "NONE"
    assert result["future_hidden_execution_artifacts"] == 0

    readme = sample_dir / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
    refused = project.materialize_sample(SAMPLE_ID, apply=True)
    assert refused.applied is False
    assert "refusing to overwrite" in refused.error
