import json
from pathlib import Path

import yaml

from qlibx.cli import run


def output(capsys: object) -> object:
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    return json.loads(captured.out)


def test_project_init_preview_and_apply_cli(tmp_path: Path, capsys: object) -> None:
    root = tmp_path / "research"
    assert run(["project", "init", str(root)]) == 0
    preview = output(capsys)
    assert preview["applied"] is False
    assert not root.exists()

    assert run(["project", "init", str(root), "--apply"]) == 0
    applied = output(capsys)
    assert applied["applied"] is True
    assert (root / "qlibx.yaml").is_file()


def test_dataset_registration_and_status_cli(tmp_path: Path, capsys: object) -> None:
    root = tmp_path / "research"
    run(["project", "init", str(root), "--apply"])
    output(capsys)
    (root / "market.csv").write_text(
        "DATE,CODE,VALUE\n2025-01-02,005930,10.0\n",
        encoding="utf-8",
    )
    registration = tmp_path / "registration.yaml"
    registration.write_text(
        yaml.safe_dump(
            {
                "dataset_id": "market",
                "source": "market.csv",
                "source_format": "csv",
                "instrument_field": "CODE",
                "source_timezone": "UTC",
                "available_at": {"kind": "field", "field": "DATE"},
                "logical_key": ["DATE", "CODE"],
                "semantic_bindings": {"value": "VALUE"},
                "source_provenance": "CLI fixture",
            }
        ),
        encoding="utf-8",
    )

    assert run(["dataset", "register", str(root), str(registration)]) == 0
    registered = output(capsys)
    assert registered["status"] == "complete"

    assert run(["project", "status", str(root)]) == 0
    status = output(capsys)
    assert status["datasets"][0]["dataset_id"] == "market"


def test_onboarding_cli_defaults_to_preview(tmp_path: Path, capsys: object) -> None:
    run(["project", "init", str(tmp_path), "--apply"])
    output(capsys)

    assert run(["project", "onboard", str(tmp_path), "--target", "codex"]) == 0
    result = output(capsys)
    assert result[0]["applied"] is False
    assert not (tmp_path / ".agents").exists()


def test_onboarding_cli_remove_is_preview_first(tmp_path: Path, capsys: object) -> None:
    assert run(["project", "init", str(tmp_path), "--apply"]) == 0
    output(capsys)
    assert run(["project", "onboard", str(tmp_path), "--target", "codex", "--apply"]) == 0
    output(capsys)
    skill = tmp_path / ".agents" / "skills" / "qlibx" / "SKILL.md"
    assert skill.exists()

    assert run(["project", "onboard", str(tmp_path), "--target", "codex", "--remove"]) == 0
    preview = output(capsys)[0]
    assert preview["desired_state"] == "absent"
    assert preview["applied"] is False
    assert preview["validation"]["matches_desired_state"] is False
    assert preview["validation_argv"][-1] == "--remove"
    assert skill.exists()

    assert (
        run(
            [
                "project",
                "onboard",
                str(tmp_path),
                "--target",
                "codex",
                "--remove",
                "--apply",
            ]
        )
        == 0
    )
    removed = output(capsys)[0]
    assert removed["applied"] is True
    assert removed["validation"]["matches_desired_state"] is True
    assert not skill.exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_strategy_validate_and_list_cli(tmp_path: Path, capsys: object) -> None:
    root = tmp_path / "strategy-project"
    assert run(["project", "init", str(root), "--apply"]) == 0
    output(capsys)
    module = root / "qlibx_extensions" / "static_strategy.py"
    module.write_text(
        "from qlibx import (\n"
        "    BudgetMode, StrategyDraft, StrategyExtensionSpec, WeightEntry,\n"
        ")\n\n"
        "STRATEGY_SPEC = StrategyExtensionSpec(strategy_id='project.cli')\n\n"
        "class Strategy:\n"
        "    strategy_id = STRATEGY_SPEC.strategy_id\n"
        "    def requirements(self):\n"
        "        return ()\n"
        "    def run(self, view):\n"
        "        return StrategyDraft(\n"
        "            weights=(WeightEntry(instrument='A', weight=1.0),),\n"
        "            budget_mode=BudgetMode.FIXED,\n"
        "            target_gross=1.0,\n"
        "        )\n\n"
        "def create_strategy():\n"
        "    return Strategy()\n",
        encoding="utf-8",
    )
    request = tmp_path / "strategy-request.yaml"
    request.write_text(
        yaml.safe_dump(
            {
                "invocation_id": "cli-strategy-validation",
                "strategy_id": "project.cli",
                "module_path": "static_strategy.py",
                "evaluation_time": "2025-01-03T09:00:00Z",
                "config_fingerprint": "cli-strategy-v1",
            }
        ),
        encoding="utf-8",
    )

    assert run(["strategy", "validate", str(root), str(request)]) == 0
    validated = output(capsys)
    registration_id = validated["result"]["registration_artifact_id"]
    assert validated["status"] == "complete"

    assert run(["strategy", "list", str(root)]) == 0
    registered = output(capsys)
    assert registered[0]["registration_artifact_id"] == registration_id
    assert registered[0]["registration"]["strategy_id"] == "project.cli"
