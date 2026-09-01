"""An interrupted write leaves the target exactly as it was, at all four former call sites.

Four implementations of "stage beside the target, fsync, `os.replace`" existed, and they had each
independently decided what to do about the parts that are easy to forget. Only `workspace.py`
retried the swap, and the reasoning for it -- `os.replace` onto a path a reader holds open fails
with `WinError 5` on Windows, readers take no lock deliberately, measured at 1 run in 10 with eight
concurrent processes -- is about `os.replace`, not about workspaces. The other three were exposed to
a race the fourth had already measured and solved.

Only two of the four fsynced; `run_records.finish` did not, on the package's crash-safety-critical
path, with nothing documenting that as a choice.

What each caller keeps is what was never about durability: its own failure vocabulary
(`on_error`), a content-addressed store's verification hook (`verify`), and whether the parent
directory's absence is a signal (`create_parent`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr._internal import atomic
from vqapr.flow.run_records import RunRecordTaken, RunRecordWriter
from vqapr.workspace import Workspace

EXPLODE = "the write failed after staging and before the swap"


class _Boom(Exception):
    pass


def test_a_failure_before_the_swap_leaves_the_target_untouched(tmp_path: Path) -> None:
    """The core contract every caller depends on: the previous file survives intact."""
    target = tmp_path / "existing.json"
    target.write_bytes(b'{"before": true}\n')

    def explode(_written: bytes) -> None:
        raise _Boom(EXPLODE)

    with pytest.raises(_Boom):
        atomic.write_atomically(target, b'{"after": true}\n', verify=explode)

    assert target.read_bytes() == b'{"before": true}\n', "a failed write must not damage the target"
    assert not list(tmp_path.glob(".*.tmp")), "and must not leave its staging file behind"


def test_a_failure_before_the_swap_creates_nothing_when_there_was_nothing(tmp_path: Path) -> None:
    """The same contract where the target did not exist: no half-written file appears."""
    target = tmp_path / "never.json"

    def explode(_written: bytes) -> None:
        raise _Boom(EXPLODE)

    with pytest.raises(_Boom):
        atomic.write_atomically(target, b"payload", verify=explode)

    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_the_workspace_survives_an_interrupted_write(tmp_path: Path) -> None:
    """Former call site 1 of 2 (`workspace.py`). A registered workspace stays readable."""
    workspace = Workspace.create(tmp_path)
    before = workspace.path.read_bytes()

    def explode(_written: bytes) -> None:
        raise _Boom(EXPLODE)

    with pytest.raises(_Boom):
        atomic.write_atomically(workspace.path, b"corrupt: [", verify=explode)

    assert workspace.path.read_bytes() == before
    assert Workspace.open(tmp_path) is not None, "and the workspace still opens"


def test_a_run_record_survives_an_interrupted_write(tmp_path: Path) -> None:
    """Former call site 2 of 2 (`run_records.py`)."""
    writer = RunRecordWriter(tmp_path, "interrupted")
    writer.open()
    target = writer.directory / "record.json"

    def explode(_written: bytes) -> None:
        raise _Boom(EXPLODE)

    with pytest.raises(_Boom):
        atomic.write_atomically(target, b"{ broken", verify=explode, create_parent=False)

    assert not target.exists(), "no partial record is left where a reader would find one"
    assert not list(writer.directory.glob(".*.tmp"))


def test_a_stolen_run_directory_is_still_reported_rather_than_recreated(tmp_path: Path) -> None:
    """`create_parent=False` is load-bearing, and this is why.

    `finish` writes into a directory claimed at the start of the run. If it is gone by the end,
    another run took the id -- only possible when someone forced an id already in use -- and this
    run's rows went with it. The shared writer creates parent directories by default, which would
    have turned that detection into a silent re-claim of state another run now owns.
    """
    import shutil

    writer = RunRecordWriter(tmp_path, "stolen")
    writer.open()
    shutil.rmtree(writer.directory)

    with pytest.raises(RunRecordTaken):
        writer.finish({"period": {}})


def test_a_finished_record_is_valid_json_with_the_newline_it_was_given(tmp_path: Path) -> None:
    """The write path still produces what readers expect, end to end.

    Text now goes through the shared writer as encoded bytes, so a `str` payload lands with the
    newlines it already carries. Two of the four former writers opened in text mode with the
    platform default, which on Windows silently translated `\\n` to `\\r\\n`.
    """
    writer = RunRecordWriter(tmp_path, "complete")
    writer.open()

    path = writer.finish({"period": {"occurrences": 3}})
    raw = path.read_bytes()

    assert json.loads(raw.decode("utf-8"))["run_id"] == "complete"
    assert raw.endswith(b"\n")
    assert b"\r\n" not in raw, "the artifact is byte-identical across platforms now"
