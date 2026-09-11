"""Record `266`: `vqapr export` writes one strategy record as files a user or a script reads.

The incremental testbed's three vqapr agents each hand-wrote an exporter for a daily NAV and a
log, and each broke on the way (tuple keys in `json.dumps`, `Decimal += str`, `str < int`, a NAV
of NaN). The command writes what the record and the report already hold: `nav.csv` IS the
report's `performance.nav`, the tables are as recorded, and every number is exact decimal text.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.cli.test_commands import _cli, _workspace_for_run
from vqapr.public import read_strategy_table, strategy_report

_NUMBERS = ("requested_quantity", "dealt_quantity", "price", "cash_delta", "commission", "tax")


def _ran(root: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    _workspace_for_run(root, capsys)
    code, ran = _cli(capsys, "--project-root", str(root), "run", "r1")
    assert code == 0, ran
    return root / ".vqapr"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_writes_the_reports_nav_and_the_tables_as_exact_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _ran(tmp_path, capsys)
    out = tmp_path / "outputs"

    code, exported = _cli(
        capsys, "--project-root", str(tmp_path), "export", "r1/my-alpha", "--out", str(out)
    )

    assert code == 0, exported
    assert exported["stage"] == "strategy.export" and exported["omitted"] == {}
    written = sorted(Path(entry["path"]).relative_to(out).as_posix() for entry in exported["files"])
    assert written == ["fills.csv", "holdings.csv", "nav.csv", "report.json", "weights.csv"]

    # nav.csv is the report's series, point for point -- the opening point included.
    nav = _rows(out / "nav.csv")
    series = strategy_report(store, "r1/my-alpha").performance.nav
    assert [Decimal(row["nav"]) for row in nav] == series.values
    assert [row["event_time"] for row in nav] == [at.isoformat() for at in series.instants]
    assert all(row["date"] == row["event_time"][:10] for row in nav), "the local date"

    # The fills as recorded, every number exact text a script parses as a number.
    fills = _rows(out / "fills.csv")
    recorded = list(read_strategy_table(store, "r1/my-alpha", "vqapr.fill"))
    assert len(fills) == len(recorded) == 2
    for row, source in zip(fills, recorded, strict=True):
        for column in _NUMBERS:
            expected = source[column]
            if expected is None:
                assert row[column] == "", column
            else:
                assert Decimal(row[column]) == expected and "E" not in row[column], column
    assert '"' not in (out / "fills.csv").read_text(encoding="utf-8"), "nothing is quoted"
    assert all(Decimal(row["weight"]) > 0 for row in _rows(out / "weights.csv"))

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report == json.loads(json.dumps(strategy_report(store, "r1/my-alpha").as_record()))


def test_export_refuses_to_overwrite_unless_forced_and_names_the_record_form(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ran(tmp_path, capsys)
    out = tmp_path / "outputs"
    argv = ("--project-root", str(tmp_path), "export", "r1/my-alpha", "--out", str(out))

    assert _cli(capsys, *argv)[0] == 0
    code, refused = _cli(capsys, *argv)
    assert code != 0 and refused["ok"] is False
    assert "nav.csv" in json.dumps(refused) and "--force" in json.dumps(refused)
    code, again = _cli(capsys, *argv, "--force")
    assert code == 0, again

    elsewhere = tmp_path / "elsewhere"
    code, bare = _cli(
        capsys, "--project-root", str(tmp_path), "export", "r1", "--out", str(elsewhere)
    )
    assert code != 0 and "<run-id>/<strategy-id>@<fp8>" in json.dumps(bare)
    assert not elsewhere.exists(), "nothing is written for an address that names no record"
