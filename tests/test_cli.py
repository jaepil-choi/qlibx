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
