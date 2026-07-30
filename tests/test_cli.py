from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from qlibx.cli import dispatch, parser
from qlibx.project import Project


def test_cli_json_is_utf8_whatever_the_callers_locale_says(tmp_path: Path) -> None:
    """The JSON response declares its own encoding instead of inheriting the caller's.

    ``PYTHONIOENCODING`` and ``PYTHONUTF8`` are cleared so the child falls back to the
    locale codec, which is what an agent invoking qlibx from a plain shell gets. On a
    legacy codepage that codec cannot represent this project path, so before the CLI
    pinned its output the same command emitted undecodable bytes here and clean UTF-8 on
    a machine that happened to export one of these variables.
    """
    project = tmp_path / "한글-프로젝트"
    project.mkdir()
    environment = dict(os.environ)
    environment.pop("PYTHONIOENCODING", None)
    environment.pop("PYTHONUTF8", None)

    completed = subprocess.run(
        [sys.executable, "-m", "qlibx", "project", "init", "--root", "."],
        cwd=project,
        check=True,
        capture_output=True,
        env=environment,
    )

    payload = json.loads(completed.stdout.decode("utf-8"))
    assert Path(payload["root"]).name == "한글-프로젝트"


def test_cli_requirements_qlib_status_and_agent_skill(tmp_path, capsys) -> None:
    command = parser()
    assert (
        dispatch(command.parse_args(["data", "requirements", "--information-field", "info_1"])) == 0
    )
    assert dispatch(command.parse_args(["qlib", "status"])) == 0
    skill = tmp_path / "skill" / "SKILL.md"
    assert dispatch(command.parse_args(["agent", "skill", "--output", str(skill)])) == 0
    assert not skill.exists()
    assert (
        dispatch(
            command.parse_args(
                ["agent", "skill", "--output", str(skill), "--target", "codex", "--apply"]
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "available_at" in output
    assert "pyqlib" not in output
    assert '"required": true' in output
    assert "registrations.yaml" in skill.read_text(encoding="utf-8")
    assert (skill.parent / "references" / "contracts.md").is_file()
    assert (skill.parent / "examples" / "project-api.py").is_file()
    assert (skill.parent / "examples" / "logical-dataset.yaml").is_file()
    assert (skill.parent / "examples" / "strategy-manifest.yaml").is_file()
    assert (skill.parent / "examples" / "strategy-binding.yaml").is_file()
    assert (skill.parent / "examples" / "pandas-strategy.py").is_file()
    assert (skill.parent / "examples" / "research-workflow.py").is_file()
    assert (skill.parent / "examples" / "stored-ensemble.py").is_file()
    assert (skill.parent / "examples" / "signed-execution.py").is_file()
    assert (skill.parent / "examples" / "artifact-reporting.py").is_file()
    assert (skill.parent / "examples" / "exponential-decay.py").is_file()
    assert (skill.parent / "examples" / "local-exposure-analyzer.py").is_file()
    assert (skill.parent / "examples" / "local-text-renderer.py").is_file()
    contracts = (skill.parent / "references" / "contracts.md").read_text(encoding="utf-8")
    assert "indexed by its configured datetime" in contracts
    assert "availability was already bounded" in contracts
    skill_text = skill.read_text(encoding="utf-8")
    assert "`available_at` is the only required time axis" in skill_text
    logical_example = (skill.parent / "examples" / "logical-dataset.yaml").read_text(
        encoding="utf-8"
    )
    assert "index: available_at" in logical_example
    assert "event_date" not in logical_example
    assert "qlibx errors <stage>" in skill_text
    assert "DATA_REGISTRATION" in skill_text
    assert "rerun the exact same capability request" in skill_text
    assert "do not repeat pandas contracts or store question/confirmation" in skill_text
    assert "combine_stored_weights" in skill_text
    json.loads(output.split("}\n{")[0] + "}")


def test_cli_exposes_common_requirements_and_read_only_plans(capsys) -> None:
    command = parser()
    assert dispatch(command.parse_args(["qlib", "requirements"])) == 0
    declaration = json.loads(capsys.readouterr().out)
    assert declaration["capability_id"] == "qlibx.execution.daily_close"
    assert declaration["requirements"][0]["alternatives"]

    assert (
        dispatch(
            command.parse_args(
                [
                    "alpha",
                    "exposure-plan",
                    "--metric",
                    "market_exposure",
                    "--provided-input",
                    "weights",
                ]
            )
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["read_only"] is True
    assert plan["ready"] is False
    assert plan["resolution"]["missing_requirements"] == ["market_beta"]


def test_cli_exposes_exact_versioned_extension_contract(capsys) -> None:
    command = parser()
    assert dispatch(command.parse_args(["extension", "contracts"])) == 0
    assert dispatch(command.parse_args(["extension", "contract", "exposure_analyzer"])) == 0
    output = capsys.readouterr().out
    first, second = output.split("}\n{")
    contracts = json.loads(first + "}")["contracts"]
    assert {item["contract"] for item in contracts} == {
        "signal_transform",
        "exposure_analyzer",
        "report_renderer",
    }
    contract = json.loads("{" + second)["exposure_analyzer"]
    assert contract["version"] == "1"
    assert contract["output_contract"]["type"] == "AnalysisSection"


def test_agent_instruction_is_dry_run_then_idempotent_apply(tmp_path: Path, capsys) -> None:
    Project.initialize(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("owned\n", encoding="utf-8")
    dry_run = parser().parse_args(
        ["agent", "instruction", "--root", str(tmp_path), "--target", "AGENTS.md"]
    )
    assert dispatch(dry_run) == 0
    assert target.read_text(encoding="utf-8") == "owned\n"
    capsys.readouterr()
    apply = parser().parse_args(
        [
            "agent",
            "instruction",
            "--root",
            str(tmp_path),
            "--target",
            "AGENTS.md",
            "--apply",
        ]
    )
    assert dispatch(apply) == 0
    first = target.read_text(encoding="utf-8")
    assert dispatch(apply) == 0
    assert target.read_text(encoding="utf-8") == first


def test_agent_instruction_detection_lists_supported_targets(tmp_path: Path, capsys) -> None:
    Project.initialize(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("owned", encoding="utf-8")
    args = parser().parse_args(["agent", "instruction", "--root", str(tmp_path), "--detect"])
    assert dispatch(args) == 0
    output = capsys.readouterr().out
    assert "AGENTS.md" in output
    assert "CLAUDE.md" in output
    assert '"read_only": true' in output


def test_every_leaf_command_binds_a_handler() -> None:
    """No command may fall through to another command's behavior."""

    def leaves(parser_obj, path=()):
        subparsers = [
            action
            for action in parser_obj._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        if not subparsers:
            yield path, parser_obj
            return
        for action in subparsers:
            for name, child in action.choices.items():
                yield from leaves(child, (*path, name))

    found = list(leaves(parser()))
    assert len(found) >= 15
    for path, leaf in found:
        handler = leaf.get_default("handler")
        assert callable(handler), f"command {' '.join(path)} has no handler"
