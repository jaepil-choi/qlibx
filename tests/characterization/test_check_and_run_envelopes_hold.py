"""Standing gate over `tests/characterization/check_and_run_envelopes.baseline.json`.

The one-door campaign (`docs/design/2026-09-10-one-door-for-a-run.md`) moves the judgments and
the freeze into one function. Agents read `check`'s and `run`'s envelopes by code, `key_path`,
`observed` and `fix`, so the move must not change a character of them. This baseline is what
the two verbs said on the sample door before the move -- a clean run, a datamodel run, a run
with three independent defects, a run naming a price its table lacks, and the same run after
its execution table changed -- with the run-specific noise (paths, ids, tracebacks, line numbers)
normalized. Regenerate ONLY when a change to an envelope is the intent:

    VQAPR_REGENERATE_CHECK_BASELINE=1 uv run python -m pytest tests/characterization/test_check_and_run_envelopes_hold.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import duckdb
import pytest

from vqapr.cli.main import main

BASELINE = Path(__file__).with_name("check_and_run_envelopes.baseline.json")
DECLARATIONS = Path(__file__).with_name("declarations")
"""Copied from `experiments/exp_235_the_scenario_trace/declarations` in record `278`: an
experiment is pinned to the version it measured, and this test must not follow it there."""

_BAD_RUNS = """\
runs:
  bad-run:
    instruments: [K000001, K000002, K000003]
    start: '2022-01-04T00:00:00+09:00'
    end: '2022-01-14T23:59:59+09:00'
    timezone: Asia/Seoul
    schedule: {every: 1d, at: '15:30'}
    exchange: sample-exchange
    execution: {dataset: sample-execution, trade_price: close, fill: {at: '15:30'}}
    initial_account: {cash: '100000000', mode: SIGNED, positions: {}}
    writes: sample-prices
    strategy: {component: sample-reversal-5d}
  bad-price-run:
    instruments: [K000001, K000002, K000003]
    start: '2022-01-04T00:00:00+09:00'
    end: '2022-01-14T23:59:59+09:00'
    timezone: Asia/Seoul
    schedule: {every: 1d, at: '08:00'}
    exchange: sample-exchange
    execution: {dataset: sample-execution, trade_price: open, fill: {at: '15:30'}}
    initial_account: {cash: '100000000', mode: LONG_ONLY, positions: {}}
    writes: bad-price-weights
    strategy: {component: sample-reversal-5d}
"""


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    out = capsys.readouterr().out.strip()
    return code, json.loads(out.splitlines()[-1])


def _normalized(body: object, roots: tuple[str, ...]) -> object:
    """The envelope with what differs between two identical runs removed."""
    text = json.dumps(body, ensure_ascii=False, sort_keys=True)
    for root in roots:
        for spelling in (root, root.replace("\\", "\\\\"), root.replace("\\", "/")):
            text = text.replace(spelling, "<root>")
    text = re.sub(r'"correlation_id": "[0-9a-f]+"', '"correlation_id": "<id>"', text)
    text = re.sub(r'"traceback": "(?:[^"\\]|\\.)*"', '"traceback": "<traceback>"', text)
    text = re.sub(r"\.py:\d+ \(", ".py:<n> (", text)
    return json.loads(text)


def _drop_last_day(execution: Path) -> None:
    con = duckdb.connect()
    try:
        con.execute(
            f"COPY (SELECT * FROM '{execution.as_posix()}' WHERE trade_at < "
            f"(SELECT max(trade_at) FROM '{execution.as_posix()}') ORDER BY trade_at, instrument) "
            f"TO '{(execution.parent / 'e.tmp.parquet').as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    shutil.move(execution.parent / "e.tmp.parquet", execution)


def _envelopes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    project = tmp_path / "sample"
    code, _ = _cli(capsys, "new", "sample", "--out", str(project))
    assert code == 0
    for name in ("features.yaml", "features.py"):
        shutil.copy(DECLARATIONS / name, project / name)
    (project / "bad.yaml").write_text(_BAD_RUNS, encoding="utf-8")
    root = ("--project-root", str(project))
    for declaration in ("sample.yaml", "features.yaml", "bad.yaml"):
        code, body = _cli(capsys, *root, "register", str(project / declaration))
        assert code == 0, body
    roots = (str(project), str(project.resolve()))
    seen: dict[str, object] = {}
    seen["check sample-run"] = _cli(capsys, *root, "check", "sample-run")
    seen["check sample-features-run"] = _cli(capsys, *root, "check", "sample-features-run")
    seen["check bad-run"] = _cli(capsys, *root, "check", "bad-run")
    seen["run bad-run"] = _cli(capsys, *root, "run", "bad-run")
    seen["check bad-price-run"] = _cli(capsys, *root, "check", "bad-price-run")
    seen["run bad-price-run"] = _cli(capsys, *root, "run", "bad-price-run")
    _drop_last_day(project / "execution.parquet")
    seen["check sample-run (execution table changed)"] = _cli(capsys, *root, "check", "sample-run")
    seen["run sample-run (execution table changed)"] = _cli(capsys, *root, "run", "sample-run")
    return {
        key: {"exit": code, "envelope": _normalized(body, roots)}
        for key, (code, body) in seen.items()
    }


def test_regenerating_is_opt_in_only() -> None:
    assert os.environ.get("VQAPR_REGENERATE_CHECK_BASELINE") is None


@pytest.mark.skipif(
    os.environ.get("VQAPR_REGENERATE_CHECK_BASELINE") is None, reason="regeneration is opt-in"
)
def test_regenerate_the_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    BASELINE.write_text(
        json.dumps(_envelopes(tmp_path, capsys), ensure_ascii=False, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def test_check_and_run_say_what_they_said_before_the_move(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    actual = _envelopes(tmp_path, capsys)
    assert set(actual) == set(expected)
    for key in expected:
        assert actual[key] == expected[key], f"{key} changed"
