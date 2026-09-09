"""`docs/issues/archive/060`: `vqapr rm dataset <id>` exists, and does what the skill promised.

The skill told the user to remove a dataset registration to replace a materialization's output;
`rm` had eight kinds and a dataset was not one of them. Three throw-away outputs (1.3 GB) stayed
registered, and a half-finished one could only be retried under a new id.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.main import main


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(argv)
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _panel(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT available_at, instrument, close::DOUBLE AS close FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
              (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B',  50.0),
              (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B',  51.0)
            ) AS t(available_at, instrument, close))
            TO '{path.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return path


def _dataset_block(dataset_id: str, source_id: str, path: Path) -> str:
    return f"""  {dataset_id}:
    source_id: {source_id}
    path: {path.as_posix()}
    instrument_field: instrument
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, instrument]
    fields:
      close: close
    field_types:
      close: DOUBLE
"""


@pytest.fixture
def project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    """One dataset at the user's own path, one under `.vqapr/materialized/`, one run reading
    its sessions from the first."""
    mine = _panel(tmp_path / "data" / "price_daily.parquet")
    written = _panel(tmp_path / ".vqapr" / "materialized" / "derived" / "part-000.parquet")
    (tmp_path / "models.py").write_text(
        "from vqapr import authoring as va\n\n"
        "class Never(va.StrategyModel):\n"
        "    def decide(self, call):\n"
        "        return va.Hold(reason='never')\n",
        encoding="utf-8",
    )
    declaration = tmp_path / "declaration.yaml"
    declaration.write_text(
        "datasets:\n"
        + _dataset_block("price_daily", "prices", mine)
        + _dataset_block("derived", "materialized-derived", written.parent)
        + f"""components:
  never:
    kind: strategy
    path: {(tmp_path / "models.py").as_posix()}
    object_name: Never
runs:
  daily:
    instruments: [A, B]
    start: "2024-03-05T00:00:00+09:00"
    end: "2024-03-07T00:00:00+09:00"
    sessions_from: price_daily
    timezone: Asia/Seoul
    at: "09:00"
    writes: daily-weights
    strategies:
      never: {{}}
""",
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(declaration))
    assert code == 0, payload
    return tmp_path


def test_a_dataset_a_run_takes_its_sessions_from_is_refused_naming_the_run(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, refused = _cli(capsys, "--project-root", str(project), "rm", "dataset", "price_daily")
    assert code == 1, refused
    assert refused["failures"][0]["code"] == "remove.referenced"
    assert "run 'daily' (sessions_from)" in refused["failures"][0]["observed"]
    code, listed = _cli(capsys, "--project-root", str(project), "list", "datasets")
    assert {row["dataset_id"] for row in listed["items"]} == {"price_daily", "derived"}


def test_a_materialized_dataset_is_withdrawn_with_its_chunks_and_its_source(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    chunks = project / ".vqapr" / "materialized" / "derived"
    assert chunks.is_dir()

    code, removed = _cli(capsys, "--project-root", str(project), "rm", "dataset", "derived")
    assert code == 0, removed
    assert removed["stage"] == "workspace.removed"
    assert removed["removed"] is True
    assert removed["deleted"] == str(chunks.resolve())
    assert not chunks.exists(), "the package's own output directory goes with the registration"

    code, listed = _cli(capsys, "--project-root", str(project), "list", "datasets")
    assert [row["dataset_id"] for row in listed["items"]] == ["price_daily"]
    text = (project / ".vqapr" / "workspace.yaml").read_text(encoding="utf-8")
    assert "materialized-derived" not in text, "a source nothing names goes too"

    code, again = _cli(capsys, "--project-root", str(project), "rm", "dataset", "derived")
    assert code == 0 and again["removed"] is False, "idempotent"


def test_a_dataset_at_the_users_own_path_is_withdrawn_without_touching_the_file(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = _cli(capsys, "--project-root", str(project), "rm", "run-definition", "daily")
    assert code == 0
    code, removed = _cli(capsys, "--project-root", str(project), "rm", "dataset", "price_daily")
    assert code == 0, removed
    assert "deleted" not in removed
    assert (project / "data" / "price_daily.parquet").is_file()
