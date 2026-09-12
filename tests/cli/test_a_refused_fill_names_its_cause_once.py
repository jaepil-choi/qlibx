"""A decision with no fill is refused once, with the repair its cause needs.

Report 2026-09-11 (`docs/issues/report-2026-09-11-a-decide-after-close-run-is-refused-on-every-
friday-and-the-second-refusal-points-at-the-run-end.md`): a run deciding at 15:31 and filling at
the next 15:30 `within: 1d` was refused on every Friday -- the next 15:30 is on Monday, and
`within` counts wall-clock time -- and the data's last session had no next 15:30 at all. `check`
listed all 403 under the ordering judgment and again under the freeze's code, and the second
listing told the author to widen the run end, which was wrong for 402 of them. Neither named the
end record `237` describes, between the last fill and the last decision (record `259`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.cli.main import main

_RUN = """\
runs:
  after-close:
    instruments: [K000001, K000002, K000003]
    start: '2024-12-16T00:00:00+09:00'
    end: '2024-12-31T23:59:59+09:00'
    timezone: Asia/Seoul
    schedule: {every: 1d, at: '15:31'}
    exchange: sample-exchange
    execution: {dataset: sample-execution, trade_price: close, fill: {at: '15:30', within: 1d}}
    initial_account: {cash: '100000000', mode: LONG_ONLY, positions: {}}
    writes: after-close-weights
    strategy: {component: sample-reversal-5d}
"""


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


@pytest.fixture
def refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> list[dict]:
    project = tmp_path / "sample"
    code, _ = _cli(capsys, "new", "sample", "--out", str(project))
    assert code == 0
    (project / "after-close.yaml").write_text(_RUN, encoding="utf-8")
    root = ("--project-root", str(project))
    for declaration in ("sample.yaml", "after-close.yaml"):
        code, body = _cli(capsys, *root, "register", str(project / declaration))
        assert code == 0, body
    code, body = _cli(capsys, *root, "check", "after-close")
    assert code == 1, body
    return body["failures"]


def test_each_event_is_listed_once(refused: list[dict]) -> None:
    listed = [example for failure in refused for example in failure["examples"]]

    assert len(listed) == len(set(listed)), "an event was refused twice"
    assert {failure["code"] for failure in refused} == {"execution.not_after_decision"}


def test_a_weekend_is_named_as_the_window_and_the_window_that_works(refused: list[dict]) -> None:
    (waiting,) = [failure for failure in refused if "beyond `within: 1d`" in failure["observed"]]

    assert "2024-12-20T15:31:00+09:00 to 2024-12-23T15:30:00+09:00" in waiting["observed"]
    assert "wall-clock" in waiting["fix"]
    assert 'within: "3d"' in waiting["fix"]
    assert "extend the run end" not in waiting["fix"]


def test_the_last_session_is_given_the_end_that_keeps_every_fill(refused: list[dict]) -> None:
    (tail,) = [failure for failure in refused if "before the run end" in failure["observed"]]

    assert tail["examples"] == ["after-close.schedule-2024-12-30T1531"]
    assert 'end: "2024-12-30T15:30:01+09:00"' in tail["fix"]
