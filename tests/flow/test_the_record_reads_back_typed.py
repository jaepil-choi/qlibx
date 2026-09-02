"""A run record reads back as the values it was written from.

Campaign Step 3; the testbed's A5. The record is JSONL and stays JSONL: append-only, one row per
line, a killed run leaves readable rows. What JSON cannot carry is a type -- a `Decimal` is
written as a string so it stays exact, an instant as ISO-8601 with its offset -- and a reader
that guesses from the text gets both wrong in the way the testbed met: `read_json_auto` shifted
every instant by nine hours and the panel built from it registered cleanly.

So the writer, which sees the types at the moment it stringifies them, records them beside the
table, and `read_run_table` (`vqapr.public`) decodes by that. A record written before the
sidecar existed reads back as strings, and says so by having no sidecar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from vqapr.flow.run_records import (
    TABLES_DIRECTORY,
    TYPES_SUFFIX,
    RunRecordWriter,
    read_table,
    read_typed_table,
    table_types,
)
from vqapr.public import read_run_table

SEOUL = timezone(timedelta(hours=9))
AT = datetime(2019, 7, 1, 15, 31, tzinfo=SEOUL)


def test_decimals_and_instants_come_back_as_what_they_were(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "typed")
    writer.open()
    writer.append(
        "vqapr.account",
        [
            {"instrument": "_ACCOUNT", "nav": Decimal("1000.25"), "observed_at": AT, "event_time": AT},
            {"instrument": "A", "nav": None, "observed_at": None, "event_time": AT},
        ],
    )

    rows = list(read_typed_table(tmp_path, "typed", "vqapr.account"))

    assert rows[0]["nav"] == Decimal("1000.25") and isinstance(rows[0]["nav"], Decimal)
    assert rows[0]["observed_at"] == AT and rows[0]["observed_at"].utcoffset() == timedelta(hours=9)
    assert rows[1]["nav"] is None and rows[1]["observed_at"] is None
    assert table_types(tmp_path, "typed", "vqapr.account") == {
        "instrument": "string",
        "nav": "decimal",
        "observed_at": "datetime",
        "event_time": "datetime",
    }
    # The raw reader is unchanged: exact text, no guessing, the CLI's page.
    assert next(iter(read_table(tmp_path, "typed", "vqapr.account")))["nav"] == "1000.25"
    assert read_run_table is read_typed_table


def test_the_instant_is_not_shifted_by_its_offset(tmp_path: Path) -> None:
    """The exact trap: 15:31+09:00 must not come back as 06:31 in any guise."""
    writer = RunRecordWriter(tmp_path, "tz")
    writer.open()
    writer.append("probe", [{"event_time": AT}])

    (row,) = read_typed_table(tmp_path, "tz", "probe")

    assert row["event_time"].hour == 15
    assert row["event_time"] == AT.astimezone(UTC)


def test_a_record_without_a_sidecar_reads_as_strings(tmp_path: Path) -> None:
    """A record from before the sidecar existed is readable, and honest about being untyped."""
    writer = RunRecordWriter(tmp_path, "old")
    writer.open()
    writer.append("probe", [{"nav": Decimal("1")}])
    (writer.directory / TABLES_DIRECTORY / f"probe{TYPES_SUFFIX}").unlink()

    assert table_types(tmp_path, "old", "probe") is None
    (row,) = read_typed_table(tmp_path, "old", "probe")
    assert row["nav"] == "1"


def test_a_column_seen_under_two_types_reads_as_the_strings_written(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "mixed")
    writer.open()
    writer.append("probe", [{"value": Decimal("1")}])
    writer.append("probe", [{"value": "one"}])

    assert table_types(tmp_path, "mixed", "probe") == {"value": "string"}
    assert [row["value"] for row in read_typed_table(tmp_path, "mixed", "probe")] == ["1", "one"]


def test_the_sidecar_is_written_once_per_table_for_an_ordinary_run(tmp_path: Path) -> None:
    """Rewritten only when a type is first seen or changes, never per chunk."""
    writer = RunRecordWriter(tmp_path, "steady")
    writer.open()
    sidecar = writer.directory / TABLES_DIRECTORY / f"probe{TYPES_SUFFIX}"
    writer.append("probe", [{"n": 1, "when": AT}])
    first = sidecar.stat().st_mtime_ns
    writer.append("probe", [{"n": 2, "when": AT}])
    writer.append("probe", [{"n": 3, "when": AT}])

    assert sidecar.stat().st_mtime_ns == first
