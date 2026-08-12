import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from qlibx import QlibxProject
from qlibx.config import ChangeAction

SAMPLE_ID = "forward-label-materialization-v1"


def _run_sample(
    script: Path,
    project_root: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, object]:
    completed = runner((script, project_root), check=True, cwd=project_root)
    return json.loads(completed.stdout)


def test_installed_forward_label_sample_closes_pit_requirement(
    tmp_path: Path,
    run_python_subprocess: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    root = tmp_path / "forward-label-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample(SAMPLE_ID)
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)
    applied = project.materialize_sample(SAMPLE_ID, apply=True)
    repeated = project.materialize_sample(SAMPLE_ID, apply=True)
    assert applied.applied is repeated.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)

    sample_dir = root / "examples" / "qlibx_owned" / "forward_label_materialization"
    result = _run_sample(sample_dir / "run.py", root, run_python_subprocess)

    assert result["failure_code"] == "REQUIREMENT_NOT_RESOLVED"
    assert result["failure_stage"].endswith("requirements.horizon_end")
    assert result["failure_requirement_id"] == "label.horizon_end"
    assert len(result["retry_entries"]) == 2
    assert {item["instrument"] for item in result["retry_entries"]} == {
        "A000001",
        "A000002",
    }
    assert [item["value"] for item in result["retry_entries"]] == pytest.approx(
        [0.1, -0.05]
    )
    assert result["later_entry_count"] == 4
    assert result["future_hidden_entry_count"] == 2
    assert result["retry_resolves_error"] is True
    assert set(result["retry_dependency_roles"]) == {
        "horizon_end",
        "label_end_value",
        "label_start_value",
        "materialization_config",
        "resolves_error",
    }
    assert result["artifact_types"] == ["forward_return_label_result"]

    readme = sample_dir / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")
    refused = project.materialize_sample(SAMPLE_ID, apply=True)
    assert refused.applied is False
    assert "refusing to overwrite" in refused.error
