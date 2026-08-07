import json
import subprocess
import sys
from pathlib import Path

from qlibx import QlibxProject
from qlibx.config import ChangeAction

SAMPLE_ID = "strategy-extension-v1"


def run_sample(script: Path, project_root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(script), str(project_root)],
        check=True,
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_uc_extension_002_installed_strategy_sample_validates_registers_and_executes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "strategy-extension-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample(SAMPLE_ID)
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)
    applied = project.materialize_sample(SAMPLE_ID, apply=True)
    assert applied.applied is True

    sample_dir = root / "examples" / "qlibx_owned" / "strategy_extension"
    strategy_source = (sample_dir / "strategy.py").read_text(encoding="utf-8")
    assert "from qlibx import (" in strategy_source
    assert "from qlibx." not in strategy_source
    script = sample_dir / "run.py"

    first = run_sample(script, root)
    repeated = run_sample(script, root)

    assert first == repeated
    assert first["module_path"] == "sample_ranked_signal.py"
    assert first["weights"] == {"A005930": 1.0}
    assert first["registration_artifact_id"] in first["dependency_ids"]
    assert {
        "stored_signal_result",
        "strategy_extension_registration",
        "strategy_result",
    }.issubset(first["artifact_types"])
    registered = project.registered_strategy_extensions()
    assert len(registered) == 1
    assert registered[0].registration_artifact_id == first["registration_artifact_id"]

    installed = root / project.config.extension_dir / "sample_ranked_signal.py"
    installed.write_text(
        installed.read_text(encoding="utf-8") + "\n# user change\n",
        encoding="utf-8",
    )
    refused = subprocess.run(
        [sys.executable, str(script), str(root)],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert refused.returncode != 0
    assert "refusing to overwrite modified" in refused.stderr