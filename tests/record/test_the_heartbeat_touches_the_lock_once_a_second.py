"""Record `248`: the heartbeat touches the run lock at most once a second, not once per chunk.

`LOCK_STALE_AFTER` is two minutes, so a touch a second says "alive" a hundred times over. The
writer touched the lock on every record chunk instead -- 110 `utime` calls for a ten-decision run,
330 for thirty-seven (`experiments/exp_246`, `08_run_factor`, `10_run_stoploss`) -- and on a
network share each is a round trip. The progress file keeps its own cadence (`PROGRESS_EVERY`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.record import LOCK_FILENAME, RunRecordWriter
from vqapr.record import writer as writer_module
from vqapr.record.schema import LOCK_TOUCH_EVERY


def _row(day: int) -> dict:
    return {
        "instrument": "_ACCOUNT",
        "nav": "1000",
        "event_time": datetime(2024, 3, day, tzinfo=UTC),
    }


def test_the_heartbeat_touches_the_lock_once_a_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched: list[Path] = []
    original_utime = writer_module.os.utime

    def counting_utime(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == LOCK_FILENAME:
            touched.append(Path(path))
        return original_utime(path, *args, **kwargs)

    clock = [1000.0]
    monkeypatch.setattr(writer_module.os, "utime", counting_utime)
    monkeypatch.setattr(writer_module._time, "monotonic", lambda: clock[0])

    writer = RunRecordWriter(tmp_path / "store", "run", "strategy@00000000")
    writer.open()
    for day in range(1, 21):
        writer.append("vqapr.account", [_row(day)])
    assert len(touched) == 1, f"twenty chunks in one second touched the lock {len(touched)} times"

    clock[0] += LOCK_TOUCH_EVERY
    writer.append("vqapr.account", [_row(21)])
    assert len(touched) == 2, "a second later the next chunk touches it again"

    writer.append("vqapr.account", [])  # the empty append is the bare heartbeat
    assert len(touched) == 2, "and inside the same second it does not"
