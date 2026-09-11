"""`on: last`, written the way the template and the skills write it, is the key `on`.

Report 2026-09-11 (`docs/issues/report-2026-09-11-the-run-template-shows-on-last-unquoted-and-
uncommenting-it-makes-yaml-read-the-key-as-true.md`): uncommenting the template's `# on: last`
made PyYAML (YAML 1.1) read the key as the boolean `True`, and registration refused with
"Keys should be strings". Declarations now read YAML 1.2's booleans: `true`/`false` only
(record `262`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.cli.main import main
from vqapr.domain.errors import read_yaml_mapping

_MONTH_END = """\
runs:
  month-end:
    instruments: [K000001, K000002, K000003]
    start: '2022-01-04T00:00:00+09:00'
    end: '2022-06-30T23:59:59+09:00'
    timezone: Asia/Seoul
    agenda:
      every: 1M
      on: last
      at: '15:29'
    exchange: sample-exchange
    execution: {dataset: sample-execution, trade_price: close, fill: {at: '15:30'}}
    initial_account: {cash: '100000000', mode: LONG_ONLY, positions: {}}
    writes: month-end-weights
    strategy: {component: sample-reversal-5d}
"""


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_the_yaml_1_1_words_are_words_and_true_is_still_true(tmp_path: Path) -> None:
    path = tmp_path / "words.yaml"
    path.write_text("on: last\noff: 1\nyes: no\nflag: true\nother: False\n", encoding="utf-8")

    assert read_yaml_mapping(path, what="a declaration") == {
        "on": "last",
        "off": 1,
        "yes": "no",
        "flag": True,
        "other": False,
    }


def test_a_month_end_run_written_unquoted_registers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "sample"
    code, _ = _cli(capsys, "new", "sample", "--out", str(project))
    assert code == 0
    (project / "month-end.yaml").write_text(_MONTH_END, encoding="utf-8")
    root = ("--project-root", str(project))

    for declaration in ("sample.yaml", "month-end.yaml"):
        code, body = _cli(capsys, *root, "register", str(project / declaration))
        assert code == 0, body
    code, body = _cli(capsys, *root, "check", "month-end")
    assert code == 0, body
