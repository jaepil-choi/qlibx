"""Record `265`: the Python readers take a record's address in either spelling a user writes it.

The CLI names a strategy record `<run-id>/<strategy-id>@<fp8>` in one argument and takes the store
as a path string. The readers took the run and the ref apart and the store only as a `Path`: the
incremental testbed's sonnet agent passed the CLI's form to `strategy_report` and was refused for a
record that exists, and its opus agent passed `".vqapr"` and got `unsupported operand type(s) for
/: 'str' and 'str'` from inside the reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.record import (
    RunRecordMissing,
    RunRecordWriter,
    read_strategy_record,
    read_table,
    record_address,
    strategy_refs,
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
            "exchange": None,
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


def test_the_cli_form_and_a_string_store_read_the_same_rows(tmp_path: Path) -> None:
    store = tmp_path / ".vqapr"
    _member(store, "r1", "mom@deadbeef", 3)
    text = str(store)

    assert len(list(read_table(text, "r1/mom@deadbeef", "vqapr.account"))) == 3
    assert len(list(read_table(text, "r1/mom", "vqapr.account"))) == 3
    assert len(list(read_table(text, "r1", "vqapr.account", "mom"))) == 3
    assert table_ids(text, "r1/mom") == ("vqapr.account",)
    assert strategy_refs(text, "r1") == ("mom@deadbeef",)
    assert strategy_refs(text, "r1/mom") == ("mom@deadbeef",), "the run a strategy names"


def test_a_strategy_record_is_read_by_any_address_the_table_reads_take(tmp_path: Path) -> None:
    store = tmp_path / ".vqapr"
    _member(store, "r1", "mom@deadbeef", 2)

    for record in (
        read_strategy_record(store, "r1", "mom@deadbeef"),
        read_strategy_record(str(store), "r1/mom@deadbeef"),
        read_strategy_record(store, "r1/mom"),
        read_strategy_record(store, "r1"),
    ):
        assert record["strategy_id"] == "mom"


def test_two_names_for_one_record_are_refused_rather_than_one_picked(tmp_path: Path) -> None:
    store = tmp_path / ".vqapr"
    _member(store, "r1", "mom@deadbeef", 1)

    with pytest.raises(RunRecordMissing, match=r"names the strategy record 'mom'.*'rev'; name it once"):
        list(read_table(store, "r1/mom", "vqapr.account", "rev"))
    with pytest.raises(RunRecordMissing, match=r"one-argument form is `<run-id>/<strategy-id>`"):
        list(read_table(store, "r1/", "vqapr.account"))
    assert record_address(str(store), "r1/mom", "mom") == (store, "r1", "mom"), (
        "the same ref given twice is one address"
    )
