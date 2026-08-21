"""`vqapr declare` is the command that made a workspace reachable by typing.

`test_commands.py` drives the happy path: its `_workspace_for_run` fixture now builds an entire
runnable workspace through the CLI, which is the property this command exists for. What is pinned
here is the part a fixture cannot show — how it refuses, and the two decisions that are easy to
regress.
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


def _observations(root: Path) -> Path:
    path = root / "observation.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
              (TIMESTAMPTZ '2024-03-05 03:00:00+09', 'A', 100.0),
              (TIMESTAMPTZ '2024-03-06 03:00:00+09', 'A', 101.0)
            ) AS t(available_at, instrument, close))
            TO '{path.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return path


def _dataset_document(observation: Path) -> str:
    return f"""
datasets:
  prices:
    source_id: price-source
    path: {observation.as_posix()}
    instrument_field: instrument
    available_at: available_at
    key_fields: [available_at, instrument]
    fields: {{close: close}}
"""


def _write(root: Path, name: str, body: str) -> str:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_the_first_declaration_creates_the_workspace(tmp_path: Path, capsys) -> None:
    """`declare` is typed in an empty directory, so it must not require a workspace to exist.

    Opening the workspace up front failed here with `workspace.open.missing`, which sends a user
    to fix a directory when their file was correct.
    """
    document = _write(tmp_path, "w.yaml", _dataset_document(_observations(tmp_path)))

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "declare", document)

    assert code == 0, payload
    assert payload["declared"] == {"datasets": ["prices"]}


def test_an_agenda_takes_its_sessions_from_the_dataset_it_follows(tmp_path: Path, capsys) -> None:
    """The short path: a cadence usually follows the data it reads.

    `from_dataset` reads `Workspace.evaluation_times`, so the agenda cannot disagree with the
    dataset about which days exist.
    """
    observation = _observations(tmp_path)
    document = _write(
        tmp_path,
        "w.yaml",
        _dataset_document(observation)
        + """
agendas:
  alpha:
    role: strategy_callback
    from_dataset: prices
    at: "04:00"
    timezone: Asia/Seoul
""",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "declare", document)

    assert code == 0, payload
    assert payload["declared"]["agendas"] == ["alpha"]

    code, listed = _cli(capsys, "--project-root", str(tmp_path), "list", "agendas")
    assert code == 0, listed


def test_an_agenda_must_declare_exactly_one_source_of_sessions(tmp_path: Path, capsys) -> None:
    """Both, or neither, is a question the command must not answer by guessing."""
    observation = _observations(tmp_path)
    both = _write(
        tmp_path,
        "both.yaml",
        _dataset_document(observation)
        + """
agendas:
  alpha:
    role: strategy_callback
    from_dataset: prices
    sessions: ["2024-03-05"]
    at: "04:00"
    timezone: Asia/Seoul
""",
    )

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "declare", both)

    assert code == 1
    assert "exactly one of from_dataset or sessions" in payload["error"]


def test_an_unknown_section_is_named_rather_than_ignored(tmp_path: Path, capsys) -> None:
    """A typo in a section name must not silently declare nothing and report success."""
    document = _write(tmp_path, "w.yaml", "dataset:\n  prices: {}\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "declare", document)

    assert code == 1
    assert "unknown section(s): dataset" in payload["error"]


def test_a_document_that_is_not_a_mapping_is_refused(tmp_path: Path, capsys) -> None:
    document = _write(tmp_path, "w.yaml", "- prices\n- venue\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "declare", document)

    assert code == 1
    assert "must be a YAML mapping" in payload["error"]


def test_every_section_is_optional(tmp_path: Path, capsys) -> None:
    """The file grows with the workspace instead of demanding everything at once."""
    document = _write(tmp_path, "w.yaml", "agendas: {}\n")

    code, payload = _cli(capsys, "--project-root", str(tmp_path), "declare", document)

    assert code == 0, payload
    assert payload["declared"] == {}
