"""A run record reads back as the values it was written from -- through this package and through duckdb.

Campaign Step 3 (record `135`) made the record stream and carry its types beside the rows, in a
`.types.json` sidecar, because the rows were JSONL and JSON cannot carry a type: a reader that
guessed from the text shifted every instant by nine hours and the panel built from it registered
cleanly (the testbed's A5). Deletion campaign Step 5 (record `146`) made the tables parquet, so
the type travels IN the file: an instant is a `timestamp[us, tz]` that comes back as the same
instant in the same zone through pyarrow and through `duckdb.read_parquet` alike, and a
`Decimal` is text the column's field metadata marks as decimal, restored by `read_table` and
exact for anyone else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.flow.record import (
    COMPACT_FILENAME,
    PART_SUFFIX,
    TABLES_DIRECTORY,
    RunRecordWriter,
    read_table,
    read_typed_table,
    table_ids,
)
from vqapr.public import read_strategy_table

SEOUL = timezone(timedelta(hours=9))
AT = datetime(2019, 7, 1, 15, 31, tzinfo=SEOUL)


def test_decimals_and_instants_come_back_as_what_they_were(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "typed")
    writer.open()
    writer.append(
        "vqapr.account",
        [
            {
                "instrument": "_ACCOUNT",
                "nav": Decimal("1000.25"),
                "observed_at": AT,
                "event_time": AT,
            },
            {"instrument": "A", "nav": None, "observed_at": None, "event_time": AT},
        ],
    )
    writer.release()

    rows = list(read_typed_table(tmp_path, "typed", "vqapr.account"))

    assert rows[0]["nav"] == Decimal("1000.25") and isinstance(rows[0]["nav"], Decimal)
    assert rows[0]["observed_at"] == AT and rows[0]["observed_at"].utcoffset() == timedelta(hours=9)
    assert rows[1]["nav"] is None and rows[1]["observed_at"] is None
    # The type travels in the parquet itself: a Decimal is text marked decimal in the field's
    # metadata, an instant is a zoned timestamp, and a string is a string.
    schema = pq.read_schema(
        writer.directory / TABLES_DIRECTORY / "vqapr.account" / COMPACT_FILENAME
    )
    assert pa.types.is_string(schema.field("instrument").type)
    assert pa.types.is_string(schema.field("nav").type)
    assert schema.field("nav").metadata == {b"vqapr.type": b"decimal"}
    assert pa.types.is_timestamp(schema.field("observed_at").type)
    assert pa.types.is_timestamp(schema.field("event_time").type)
    assert read_strategy_table is read_typed_table is read_table
    assert table_ids(tmp_path, "typed") == ("vqapr.account",)


def test_the_instant_is_not_shifted_by_its_offset_through_duckdb_either(tmp_path: Path) -> None:
    """The exact trap: 15:31+09:00 must not come back as 06:31 in any guise, in any reader."""
    writer = RunRecordWriter(tmp_path, "tz")
    writer.open()
    writer.append("probe", [{"event_time": AT, "nav": Decimal("1")}])
    writer.release()

    (row,) = read_typed_table(tmp_path, "tz", "probe")
    assert row["event_time"].hour == 15
    assert row["event_time"] == AT.astimezone(UTC)

    compact = writer.directory / TABLES_DIRECTORY / "probe" / COMPACT_FILENAME
    (through_duckdb,) = (
        duckdb.connect()
        .execute(
            "SELECT epoch_us(event_time), typeof(event_time), nav "
            f"FROM read_parquet('{compact.as_posix()}')"
        )
        .fetchall()
    )
    assert through_duckdb[0] == int(AT.timestamp() * 1_000_000)
    assert through_duckdb[1] == "TIMESTAMP WITH TIME ZONE"
    assert through_duckdb[2] == "1", "a Decimal is exact text for a reader outside this package"


def test_a_decimal_weight_of_one_third_keeps_every_digit(tmp_path: Path) -> None:
    """Why a Decimal is text and not a parquet decimal: no fixed scale would hold it."""
    third = Decimal(1) / Decimal(3)
    writer = RunRecordWriter(tmp_path, "third")
    writer.open()
    writer.append("vqapr.weight", [{"instrument": "A", "weight": third, "event_time": AT}])
    writer.release()

    (row,) = read_table(tmp_path, "third", "vqapr.weight")
    assert row["weight"] == third


def test_a_table_is_one_file_written_when_the_run_ends_and_a_column_keeps_its_first_type(
    tmp_path: Path,
) -> None:
    """Nothing reaches the disk per chunk (`087`); at `release` every chunk is one file, and a
    null-first column is typed by the first value that typed it."""
    writer = RunRecordWriter(tmp_path, "chunks")
    writer.open()
    writer.append("probe", [{"n": 1, "when": None}])
    writer.append("probe", [{"n": 2, "when": AT}])
    writer.append("probe", [{"n": 3, "when": AT + timedelta(days=1)}])

    directory = writer.directory / TABLES_DIRECTORY / "probe"
    assert not directory.exists(), "a running writer holds its rows in memory"
    assert list(read_table(tmp_path, "chunks", "probe")) == []

    writer.release()

    assert sorted(path.name for path in directory.iterdir()) == [COMPACT_FILENAME]
    rows = list(read_table(tmp_path, "chunks", "probe"))
    assert [row["n"] for row in rows] == [1, 2, 3]
    assert rows[0]["when"] is None and rows[1]["when"] == AT
    schema = pq.read_schema(directory / COMPACT_FILENAME)
    assert pa.types.is_integer(schema.field("n").type)
    assert pa.types.is_timestamp(schema.field("when").type), (
        "a null-first column is typed by the first value that typed it"
    )


def test_a_buffer_over_the_spill_line_lands_as_parts_that_the_end_folds_into_one_file(
    tmp_path: Path,
) -> None:
    """The safety valve: above `spill_bytes` a part is written, and `release` folds every part
    and what is still buffered into `all.parquet`, in order, then removes the parts."""
    writer = RunRecordWriter(tmp_path, "spilled", spill_bytes=1)
    writer.open()
    writer.append("probe", [{"n": 1, "when": None}])
    writer.append("probe", [{"n": 2, "when": AT}])
    directory = writer.directory / TABLES_DIRECTORY / "probe"
    assert sorted(path.name for path in directory.iterdir()) == [
        "000000.parquet",
        "000001.parquet",
    ]
    assert [row["n"] for row in read_table(tmp_path, "spilled", "probe")] == [1, 2], (
        "a hard-killed run keeps its spill parts, and a reader reads them"
    )

    writer.release()

    assert sorted(path.name for path in directory.iterdir()) == [COMPACT_FILENAME]
    rows = list(read_table(tmp_path, "spilled", "probe"))
    assert [row["n"] for row in rows] == [1, 2] and rows[1]["when"] == AT
    assert pa.types.is_timestamp(pq.read_schema(directory / COMPACT_FILENAME).field("when").type)


def test_a_compact_file_beside_leftover_parts_is_read_alone(tmp_path: Path) -> None:
    """A seal interrupted between writing `all.parquet` and removing the parts must not double
    the rows: the compact file is the table, the parts were its input."""
    writer = RunRecordWriter(tmp_path, "interrupted", spill_bytes=1)
    writer.open()
    writer.append("probe", [{"n": 1}])
    writer.append("probe", [{"n": 2}])
    directory = writer.directory / TABLES_DIRECTORY / "probe"
    leftover = (directory / "000000.parquet").read_bytes()
    writer.release()
    (directory / "000000.parquet").write_bytes(leftover)

    assert [row["n"] for row in read_table(tmp_path, "interrupted", "probe")] == [1, 2]


def test_a_column_seen_under_two_kinds_is_refused_at_the_write(tmp_path: Path) -> None:
    """The recorder wrote both, so the run's own table is what is wrong; nothing downgrades."""
    writer = RunRecordWriter(tmp_path, "mixed")
    writer.open()
    writer.append("probe", [{"value": Decimal("1")}])

    with pytest.raises(ValueError, match="column 'value'"):
        writer.append("probe", [{"value": "one"}])
    with pytest.raises(ValueError, match="two kinds"):
        writer.append("other", [{"value": Decimal("1")}, {"value": "one"}])


def test_a_damaged_chunk_is_reported_not_skipped(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "damaged")
    writer.open()
    writer.append("probe", [{"n": 1}])
    writer.release()
    (part,) = (writer.directory / TABLES_DIRECTORY / "probe").glob(f"*{PART_SUFFIX}")
    part.write_bytes(b"not parquet")

    with pytest.raises(ValueError, match="not a parquet file"):
        list(read_table(tmp_path, "damaged", "probe"))


def test_a_table_never_written_reads_as_no_table(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "empty")
    writer.open()
    writer.append("probe", [])

    assert table_ids(tmp_path, "empty") == ()
    assert list(read_table(tmp_path, "empty", "probe")) == []
