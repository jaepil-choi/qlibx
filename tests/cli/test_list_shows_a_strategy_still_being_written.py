"""`vqapr list strategies --run <id>` shows a strategy that has no record yet.

`docs/issues/074`: a strategy's record is written last, `list` read records only, and `show`
refused a record still being written -- so for the eleven minutes a run took, nothing on the
surface said how far each strategy had got, and an author counted parquet files by hand. One of
the eight had stopped advancing, and the count could not say whether it was dead or slow.

The rows here are written by a `RunRecordWriter` directly, the way a run writes them, so the test
can put the directory into each of the states a reader may find it in.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.cli.main import main
from vqapr.flow.run_records import LOCK_FILENAME, RunRecordWriter

REF = "never-ready@abcdef12"


def _list(capsys: pytest.CaptureFixture[str], project: Path, store: Path, *extra: str) -> dict:
    code = main(
        [
            "--project-root", str(project),
            "list", "strategies", "--run", "mixed", "--store-root", str(store),
            *extra,
        ]
    )
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0, payload
    return payload


def _row(event_time: datetime) -> dict:
    return {"instrument": "_ACCOUNT", "nav": "1000", "event_time": event_time}


def test_a_strategy_being_written_is_listed_as_running_with_its_progress(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    writer = RunRecordWriter(store, "mixed", REF)
    writer.open()
    first = datetime(2024, 3, 5, 15, 30, tzinfo=UTC)
    second = datetime(2024, 3, 6, 15, 30, tzinfo=UTC)
    writer.append("vqapr.account", [_row(first)])
    writer.append("vqapr.account", [_row(second)])
    writer.append("vqapr.weight", [{"instrument": "A", "weight": "0.5", "event_time": second}])

    listed = _list(capsys, tmp_path, store)

    assert listed["count"] == 1
    (row,) = listed["items"]
    assert row["strategy_ref"] == REF and row["strategy_id"] == "never-ready"
    assert row["status"] == "running"
    assert row["fingerprint"] is None, "only the <fp8> in the ref is known before the record"
    assert row["chunks"] == 2, "one part per accepted session, the most any table has"
    assert row["tables"] == ["vqapr.account", "vqapr.weight"]
    assert datetime.fromisoformat(row["last_event_time"]) == second
    assert row["lock"]["pid"] == os.getpid()
    assert 0 <= row["lock"]["refreshed_ago"] < 60

    # The filters a reader uses on finished rows work on this one too.
    assert _list(capsys, tmp_path, store, "--strategy", "other")["count"] == 0
    assert _list(capsys, tmp_path, store, "--fingerprint", "abcd")["count"] == 1
    assert _list(capsys, tmp_path, store, "--since", "2024-03-07T00:00:00+00:00")["count"] == 0
    assert _list(capsys, tmp_path, store, "--since", "2024-03-06T00:00:00+00:00")["count"] == 1
    assert _list(capsys, tmp_path, store, "--failed-contract")["count"] == 0, (
        "an unfinished strategy has no contract to have failed"
    )


def test_a_strategy_whose_lock_went_quiet_is_listed_as_unfinished(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A killed strategy and a refused one leave the same directory: rows, no record, a lock
    nobody touches. The listing says `unfinished`; the run's envelope says which it was."""
    store = tmp_path / "store"
    writer = RunRecordWriter(store, "mixed", REF)
    writer.open()
    writer.append("vqapr.account", [_row(datetime(2024, 3, 5, 15, 30, tzinfo=UTC))])
    lock = store / "runs" / "mixed" / "strategies" / REF / LOCK_FILENAME
    stale = time.time() - 600
    os.utime(lock, (stale, stale))

    (row,) = _list(capsys, tmp_path, store)["items"]

    assert row["status"] == "unfinished"
    assert row["lock"] is None
    assert row["chunks"] == 1 and row["last_event_time"].startswith("2024-03-05")

    writer.release()
    (row,) = _list(capsys, tmp_path, store)["items"]
    assert row["status"] == "unfinished" and row["lock"] is None
