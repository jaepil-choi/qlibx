"""`docs/issues/080`: the datamodel side of `074`.

A datamodel run that dies inside a callback leaves `<id>@<fp8>/tables/` and no `datamodel.json`.
`list datamodels --run` showed finished records only, so the directory was invisible; `rm
datamodel` resolved a member through the finished set, so it could not be named; and the skill's
"count the directories" then over-counted a model's tunings by its crashes. The strategy side had
all three answers since record `150`; this gives the datamodel side the same shape.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.cli.main import main
from vqapr.flow.run_records import DATAMODEL_KIND, LOCK_FILENAME, RunRecordWriter

REF = "alpha-revision-010@8e6a2fe3"


def _cli(capsys: pytest.CaptureFixture[str], project: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--project-root", str(project), *argv])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _crashed_datamodel(store: Path) -> Path:
    """Rows written the way a datamodel run writes them, then the writer goes quiet."""
    writer = RunRecordWriter(store, "alphas", REF, member_kind=DATAMODEL_KIND)
    writer.open()
    writer.append(
        "vqapr.datamodel",
        [
            {
                "instrument": "A",
                "score": "0.1",
                "event_time": datetime(2024, 3, 5, 15, 30, tzinfo=UTC),
            }
        ],
    )
    lock = store / "runs" / "alphas" / "datamodels" / REF / LOCK_FILENAME
    stale = time.time() - 600
    os.utime(lock, (stale, stale))
    return lock.parent


def test_a_crashed_datamodel_directory_is_listed_as_unfinished_with_its_progress(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    _crashed_datamodel(store)

    code, listed = _cli(
        capsys, tmp_path, "list", "datamodels", "--run", "alphas", "--store-root", str(store)
    )

    assert code == 0, listed
    (row,) = listed["items"]
    assert row["datamodel_ref"] == REF and row["datamodel_id"] == "alpha-revision-010"
    assert row["status"] == "unfinished"
    assert row["lock"] is None
    assert row["chunks"] == 1 and row["tables"] == ["vqapr.datamodel"]
    assert row["last_event_time"].startswith("2024-03-05")
    assert row["fingerprint"] is None and row["dataset_id"] is None and row["rows"] is None


def test_rm_datamodel_names_a_directory_that_has_no_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one a reader wants to remove is exactly the one that has no record to resolve."""
    store = tmp_path / "store"
    directory = _crashed_datamodel(store)
    assert directory.is_dir()

    code, removed = _cli(
        capsys, tmp_path, "rm", "datamodel", f"alphas/{REF}", "--store-root", str(store)
    )

    assert code == 0, removed
    assert removed["stage"] == "record.removed" and removed["removed"] == [REF]
    assert not directory.exists()
    code, listed = _cli(
        capsys, tmp_path, "list", "datamodels", "--run", "alphas", "--store-root", str(store)
    )
    assert listed["count"] == 0
