"""`vqapr new sample --out DIR` is the door PRD §11.4 promised (record `172`).

One command writes a journey the product can run as it is; the next two verbs are the ones every
user runs on their own declarations. No warehouse, no build step: the panel ships in the wheel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_commands import _cli

from vqapr.agent.sample.materialize import DATA_FILES, RUN_ID


def _new_sample(capsys: pytest.CaptureFixture[str], root: Path, out: Path) -> dict:
    code, payload = _cli(capsys, "--project-root", str(root), "new", "sample", "--out", str(out))
    assert code == 0, payload
    return payload


def test_new_sample_writes_a_registrable_journey_that_check_accepts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "first-run"

    payload = _new_sample(capsys, tmp_path, out)

    assert payload["kind"] == "sample" and payload["run_id"] == RUN_ID
    assert Path(payload["declaration"]) == out / "sample.yaml"
    assert payload["next"][0].startswith("vqapr register ")
    written = {path.name for path in out.iterdir()}
    assert {"reversal_5d.py", "exchange.py", "sample.yaml", "README.md", *DATA_FILES} <= written
    panel = json.loads((out / "panel.json").read_text(encoding="utf-8"))
    assert panel["synthetic"] is True, "the shipped panel must say it is not market data"

    code, registered = _cli(
        capsys, "--project-root", str(tmp_path), "register", str(out / "sample.yaml")
    )
    assert code == 0, registered
    assert registered["registered"]["runs"] == [RUN_ID]

    code, checked = _cli(capsys, "--project-root", str(tmp_path), "check", RUN_ID)
    assert code == 0, checked
    # A clean check is a success envelope: no `failures` key, nothing blocked or skipped.
    assert checked["ok"] is True and checked["blocked"] == [] and checked["skipped"] == []


def test_new_sample_refuses_to_overwrite_a_directory_that_holds_something(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "first-run"
    out.mkdir()
    (out / "mine.txt").write_text("keep", encoding="utf-8")

    code, payload = _cli(
        capsys, "--project-root", str(tmp_path), "new", "sample", "--out", str(out)
    )

    assert code == 1
    (failure,) = payload["failures"]
    assert failure["status"] == 409 and failure["code"] == "argument.file_exists"
    assert (out / "mine.txt").read_text(encoding="utf-8") == "keep"
    assert not (out / "sample.yaml").exists()
