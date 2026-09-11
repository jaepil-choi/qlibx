"""A run record written before vqapr 0.16.0 is refused, and the refusal says to re-run it.

Owner ruling 2026-09-12 (record `278`, option A): the loop's vocabulary changed -- `agenda` is
`schedule`, `occurrence` is `event` -- and an old record is not translated on the way in. The run,
strategy and datamodel schemas went to v2 together; a v1 record names the release and the way
forward, and a record from a newer vqapr says to upgrade instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vqapr.record.reader import read_run_record
from vqapr.record.schema import RUN_SCHEMA, run_record_path


def _record(root: Path, schema: str) -> None:
    path = run_record_path(root, "old")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": schema}), encoding="utf-8")


def test_a_record_written_before_the_rename_says_to_re_run(tmp_path: Path) -> None:
    _record(tmp_path, "vqapr-run/v1")
    with pytest.raises(ValueError, match="Re-run the run to record it again") as refused:
        read_run_record(tmp_path, "old")
    assert "0.16.0" in str(refused.value) and "`schedule`" in str(refused.value)


def test_a_record_from_a_newer_vqapr_says_to_upgrade(tmp_path: Path) -> None:
    _record(tmp_path, "vqapr-run/v9")
    with pytest.raises(ValueError, match="Upgrade vqapr"):
        read_run_record(tmp_path, "old")


def test_the_current_schema_is_v2() -> None:
    assert RUN_SCHEMA == "vqapr-run/v2"
