from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


def _qlibx(project: Path, *arguments: str) -> dict[str, object]:
    """Run the installed CLI as a subprocess, reporting enough to diagnose a failure.

    ``check=True`` alone raises without the child's stderr, and a stdout that is not
    JSON gives no context at all, so a transient subprocess failure is undiagnosable
    after the fact. Both paths now carry the command, exit code, stdout and stderr.

    Each stream is decoded here rather than through ``text=True``, which would use the
    locale codec and mangle the CLI's declared UTF-8 output on a legacy codepage --- the
    journey runs under ``tmp_path``, so a non-ASCII user name reaches this JSON. stderr
    can still carry bytes written before the CLI pinned its encoding (an interpreter
    warning during import, say), so it is decoded leniently: it is context for a failure,
    never the assertion.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "qlibx", *arguments],
        cwd=project,
        check=False,
        capture_output=True,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    context = (
        f"command: qlibx {' '.join(arguments)}\n"
        f"exit code: {completed.returncode}\n"
        f"stdout: {stdout!r}\n"
        f"stderr: {completed.stderr.decode('utf-8', errors='replace')!r}"
    )
    assert completed.returncode == 0, f"qlibx CLI failed\n{context}"
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"qlibx CLI did not emit JSON\n{context}") from error


def test_fresh_agent_onboarding_and_data_registration_journey(tmp_path: Path) -> None:
    _qlibx(tmp_path, "project", "init", "--root", ".")
    source = tmp_path / "data" / "incoming" / "observations.parquet"
    source.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "event_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "instrument": ["A", "A"],
            "opaque_value": [1.0, 2.0],
        }
    ).to_parquet(source, index=False)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    detected = _qlibx(tmp_path, "agent", "instruction", "--root", ".", "--detect")
    assert detected["read_only"] is True
    instruction_plan = _qlibx(
        tmp_path,
        "agent",
        "instruction",
        "--root",
        ".",
        "--target",
        "AGENTS.md",
    )
    assert instruction_plan["applied"] is False
    assert not (tmp_path / "AGENTS.md").exists()
    _qlibx(
        tmp_path,
        "agent",
        "instruction",
        "--root",
        ".",
        "--target",
        "AGENTS.md",
        "--apply",
    )

    skill_root = tmp_path / ".agents" / "skills" / "qlibx"
    skill_plan = _qlibx(
        tmp_path,
        "agent",
        "skill",
        "--target",
        "codex",
        "--output",
        str(skill_root),
    )
    assert skill_plan["applied"] is False
    assert not skill_root.exists()
    _qlibx(
        tmp_path,
        "agent",
        "skill",
        "--target",
        "codex",
        "--output",
        str(skill_root),
        "--apply",
    )
    assert (skill_root / "SKILL.md").is_file()
    assert (skill_root / "references" / "contracts.md").is_file()

    discovered = _qlibx(tmp_path, "data", "discover", "--root", ".")
    assert discovered["read_only"] is True
    assert discovered["mutates"] == []
    assert discovered["candidates"][0]["path"] == "data/incoming/observations.parquet"
    inspected = _qlibx(
        tmp_path,
        "data",
        "inspect",
        "--root",
        ".",
        "--path",
        "data/incoming/observations.parquet",
        "--sample-rows",
        "1",
    )
    assert "available_at source and rule" in inspected["unresolved_requirements"]
    assert inspected["mutates"] == []

    # The harness now represents the user's explicit answers; qlibx did not infer these mappings.
    config = tmp_path / "config" / "qlibx" / "data"
    datasets = config / "datasets"
    datasets.mkdir(parents=True)
    (config / "registrations.yaml").write_text(
        """registrations:
  observations:
    source: data/incoming/observations.parquet
    output: data/qlibx/observations.parquet
    available_at: {source: event_date, offset_days: -1}
    ticker: instrument
    information: {event_date: event_date, info_1: opaque_value}
    primary_key: [event_date, instrument]
    frequency: daily
    timezone: Asia/Seoul
""",
        encoding="utf-8",
    )
    (config / "base.yaml").write_text(
        """schema_version: 1
paths: {canonical: data/qlibx}
catalog:
  source_file: sources.yaml
  dataset_files: [datasets/observations.yaml]
""",
        encoding="utf-8",
    )
    (config / "sources.yaml").write_text(
        "parquet_sources:\n  observations: {root: canonical, path: observations.parquet}\n",
        encoding="utf-8",
    )
    (datasets / "observations.yaml").write_text(
        """datasets:
  observations:
    kind: matrix
    sources: [observations]
    query: select available_at, event_date, ticker, info_1 from observations
    index: event_date
    columns: ticker
    values: info_1
    time_field: event_date
    availability_field: available_at
    dtype: float64
""",
        encoding="utf-8",
    )

    planned = _qlibx(tmp_path, "data", "plan", "--root", ".", "--dataset", "observations")
    assert planned["availability"]["offset_days"] == -1
    registered = _qlibx(tmp_path, "data", "register", "--root", ".", "--dataset", "observations")
    assert registered["information_values_preserved"] is True
    catalog = _qlibx(tmp_path, "data", "catalog", "--root", ".")
    assert "observations" in catalog["datasets"]
    preview = _qlibx(
        tmp_path,
        "data",
        "preview",
        "--root",
        ".",
        "--dataset",
        "observations",
        "--start",
        "2025-01-02",
        "--end",
        "2025-01-03",
        "--as-of",
        "2025-01-01",
        "--limit",
        "5",
    )
    assert preview["rows"] == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert (tmp_path / "data" / "qlibx" / "observations.parquet").is_file()
    assert (tmp_path / ".qlibx" / "registrations" / "observations.json").is_file()
