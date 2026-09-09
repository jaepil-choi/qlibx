"""`docs/issues/archive/057`: a table read that points at nothing is refused, naming what exists.

`read_strategy_table(store_root, run_id, table, strategy_ref)` returned an empty iterator for
the project directory (the root is `<project>/.vqapr`), for `strategy_ref=None` on a current
record, and for the bare `<strategy-id>` the CLI accepts. The user's code failed three steps
later on an empty frame. An empty TABLE stays empty -- a declared table nobody wrote is a fact
about the run -- but a missing RECORD is a wrong argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.record import (
    RunRecordMissing,
    RunRecordWriter,
    read_table,
    table_ids,
)


def _member(root: Path, run_id: str, ref: str, rows: int) -> None:
    writer = RunRecordWriter(root, run_id, ref)
    writer.open()
    writer.append(
        "vqapr.account",
        [{"instrument": "_ACCOUNT", "nav": f"{1000 + i}", "event_time": f"t{i}"} for i in range(rows)],
    )
    writer.finish(
        {
            "strategy_id": ref.split("@")[0],
            "fingerprint": ref.split("@")[1] * 8,
            "component": {},
            "agenda": {},
            "compliance": [],
            "account": {"version": rows, "cash": "1000", "positions": {}},
            "tables": {"vqapr.account": {"rows": rows, "instants": rows}},
            "contract": {},
            "source_digest": {},
            "declared_digest": "d",
            "roster": None,
            "period": {"start": "2024-01-01", "end": "2024-12-31", "occurrences": rows},
        },
        kind="strategy",
    )


def test_the_project_directory_is_refused_as_a_root_naming_the_runs_that_exist(
    tmp_path: Path,
) -> None:
    store = tmp_path / ".vqapr"
    _member(store, "r1", "mom@deadbeef", 2)

    with pytest.raises(RunRecordMissing, match=r"no run 'r1' under .*runs; run directories there: \(none\)"):
        list(read_table(tmp_path, "r1", "vqapr.account", "mom@deadbeef"))
    with pytest.raises(RunRecordMissing, match=r"run directories there: r1"):
        list(read_table(store, "absent", "vqapr.account", "mom@deadbeef"))


def test_a_bare_strategy_id_and_none_resolve_to_the_only_record(tmp_path: Path) -> None:
    store = tmp_path / ".vqapr"
    _member(store, "r1", "mom@deadbeef", 3)

    assert len(list(read_table(store, "r1", "vqapr.account", "mom@deadbeef"))) == 3
    assert len(list(read_table(store, "r1", "vqapr.account", "mom"))) == 3
    assert len(list(read_table(store, "r1", "vqapr.account"))) == 3
    assert table_ids(store, "r1", "mom") == ("vqapr.account",)
    # A declared-but-unwritten table is still empty, not refused: that is a fact about the run.
    assert list(read_table(store, "r1", "vqapr.fill", "mom")) == []


def test_several_fingerprints_are_listed_rather_than_guessed(tmp_path: Path) -> None:
    store = tmp_path / ".vqapr"
    _member(store, "r1", "mom@11111111", 1)
    _member(store, "r1", "mom@22222222", 2)

    with pytest.raises(RunRecordMissing, match=r"'mom' has 2 records: mom@11111111, mom@22222222"):
        list(read_table(store, "r1", "vqapr.account", "mom"))
    with pytest.raises(RunRecordMissing, match=r"records 2 strategies"):
        list(read_table(store, "r1", "vqapr.account"))
    with pytest.raises(RunRecordMissing, match=r"no strategy record 'rev'.*recorded there: mom@"):
        list(read_table(store, "r1", "vqapr.account", "rev"))
