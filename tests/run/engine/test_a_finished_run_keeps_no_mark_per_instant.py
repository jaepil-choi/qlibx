"""Record `224`: what a run keeps in memory does not grow with the market clock.

A minute table values the book 390 times a day, and every valuation is a `Mark` per held name.
Until `224` each batch hung off the run's evidence and traces until the run ended -- instants x
names objects, which for 3,000 names over a year is more than the process can hold. The marks
are `vqapr.account` rows the moment they are made, so the evidence keeps a summary and the
batch is garbage as soon as the account's retained window lets it go.

Measured on the AC-1 workspace: eleven market-clock instants, one name, decisions every minute.
Before `224` a finished result kept one `Mark` per instant; now it keeps the account's retained
mark and nothing per instant.
"""

from __future__ import annotations

import gc
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.acceptance.test_a_minute_strategy_fills_at_the_next_minute import _workspace
from tests.cli.test_commands import _cli
from vqapr.data.execution_table import ExecutionSnapshotSummary
from vqapr.domain.account import Mark, MarkSummary
from vqapr.public import Workspace, preflight_run, run
from vqapr.run.engine.evidence import AccountCommitEvidence, MarkEvidence, ValuationEvidence
from vqapr.run.engine.loop import DueExecutionTrace

_ZONE = ZoneInfo("Asia/Seoul")


@pytest.mark.slow
def test_a_finished_run_keeps_a_summary_per_instant_and_not_a_mark_per_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _workspace(tmp_path, capsys)
    runs = tmp_path / "runs.yaml"
    runs.write_text(
        json.dumps(
            {
                "runs": {
                    "kept": {
                        "writes": "kept-weights",
                        "strategy": {"component": "always-long"},
                        "timezone": "Asia/Seoul",
                        "agenda": {"every": "1m", "from": "09:00", "to": "09:05"},
                        "exchange": "venue",
                        "execution": {"dataset": "venue-minute", "trade_price": "close"},
                        "start": datetime(2024, 3, 5, 0, tzinfo=_ZONE).isoformat(),
                        "end": datetime(2024, 3, 5, 23, tzinfo=_ZONE).isoformat(),
                        "initial_account": {"cash": "1000", "mode": "long_only"},
                        "instruments": ["A"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    code, payload = _cli(capsys, "--project-root", str(tmp_path), "register", str(runs))
    assert code == 0, payload

    workspace = Workspace.open(tmp_path)
    result = run(tmp_path, preflight_run(workspace, workspace.run_definition("kept"))).result()
    gc.collect()

    market = [trace for trace in result.occurrences if isinstance(trace, DueExecutionTrace)]
    assert len(market) == 11, "eleven market-clock instants were valued"
    kept = sum(1 for item in gc.get_objects() if isinstance(item, Mark))
    assert kept <= 2, f"{kept} Mark objects survive a run of eleven valuations of one name"

    # The evidence says what the marks were worth and how many there were, not what they were.
    kinds = {type(entry.detail) for entry in result.final_state.lifecycle_trace}
    assert {ValuationEvidence, MarkEvidence, AccountCommitEvidence} <= kinds
    for entry in result.final_state.lifecycle_trace:
        detail = entry.detail
        if isinstance(detail, ValuationEvidence | MarkEvidence):
            assert isinstance(detail.marks, MarkSummary)
        if isinstance(detail, MarkEvidence):
            assert isinstance(detail.selected, int)
        if isinstance(detail, AccountCommitEvidence):
            assert isinstance(detail.execution_snapshot, ExecutionSnapshotSummary)
            assert detail.execution_snapshot.rows >= 1
