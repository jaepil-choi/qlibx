"""A run's recorded table becomes an ordinary dataset a later run can subscribe to."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.domain.errors import VqaprError
from vqapr.public import RunRecordSpec, TableSpec, publish_run_record
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class _State:
    recorder_rows: dict[str, tuple[dict[str, object], ...]]


@dataclass(frozen=True)
class _Result:
    final_state: _State


def _row(*, instrument: str, event_time: datetime, signal: str, sequence: int) -> dict[str, object]:
    """The shape the Flow actually stamps: user columns plus the five envelope fields."""
    return {
        "instrument": instrument,
        "signal": signal,
        "run_id": "run-1",
        "producer_id": "alpha",
        "stage": "STRATEGY_CALLBACK",
        "event_time": event_time,
        "sequence": sequence,
    }


def _result(cutoff: datetime) -> _Result:
    return _Result(
        _State(
            {
                "alpha.signal": (
                    _row(instrument="A", event_time=cutoff, signal="0.5", sequence=0),
                    _row(instrument="B", event_time=cutoff, signal="-0.5", sequence=1),
                )
            }
        )
    )


def _published(path: Path) -> list[tuple]:
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY available_at, instrument"
        ).fetchall()
    finally:
        con.close()


def test_a_recorded_table_publishes_as_an_ordinary_dataset(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)

    result = publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "alpha_signal",
            table_id="alpha.signal",
            value_fields=("signal", "run_id", "producer_id", "stage", "event_time", "sequence"),
        ),
        _result(cutoff),
    )

    assert result.row_count == 2
    assert result.output_path.is_file()
    assert len(_published(result.output_path)) == 2


def test_the_two_clocks_stay_two_columns(tmp_path: Path) -> None:
    """PRD 9.4 forbids collapsing them, so both survive on the published row.

    `event_time` is the occurrence the row was written at; `available_at` is when the row becomes
    visible. A publication that kept only one would leave a reader unable to tell which it had.
    """
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)

    result = publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "alpha_signal", table_id="alpha.signal", value_fields=("signal", "event_time")
        ),
        _result(cutoff),
    )

    con = duckdb.connect()
    try:
        columns = {
            row[0]
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{result.output_path.as_posix()}')"
            ).fetchall()
        }
    finally:
        con.close()

    assert {"available_at", "event_time"} <= columns, "both clocks must survive"


def test_the_envelope_rides_as_declared_value_fields(tmp_path: Path) -> None:
    """Without them the record drops PRD 9.4's which-run, whose, at-what-time obligation."""
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)

    result = publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "alpha_signal",
            table_id="alpha.signal",
            value_fields=("signal", "run_id", "producer_id", "stage", "event_time", "sequence"),
        ),
        _result(cutoff),
    )

    payload = json.loads(result.lineage_path.read_text(encoding="utf-8"))

    assert payload["operation"] == "run.record"
    assert payload["record"]["table_id"] == "alpha.signal"
    assert payload["record"]["run_identity"] == ["run-1"]
    assert {"run_id", "producer_id", "stage", "sequence"} <= set(payload["output"]["value_fields"])


def test_a_package_owned_column_cannot_be_declared() -> None:
    """The same guard the other two specs apply, for the same reason.

    A record that could name its own `available_at` would let a producer choose its stamp on the
    one publication path whose purpose is to prove it did not.
    """
    for field in ("available_at", "instrument"):
        with pytest.raises(ValueError, match="package-owned"):
            RunRecordSpec.of("d", table_id="t", value_fields=("signal", field))


def test_publishing_needs_a_run_result_and_a_recorded_table(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    spec = RunRecordSpec.of("alpha_signal", table_id="alpha.signal", value_fields=("signal",))

    with pytest.raises(VqaprError, match="recorder rows"):
        publish_run_record(tmp_path, spec, object())

    with pytest.raises(VqaprError, match="recorded no rows"):
        publish_run_record(tmp_path, spec, _Result(_State({})))


def test_a_declared_field_absent_from_a_row_is_refused(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)

    with pytest.raises(VqaprError, match="must be present on every recorded row"):
        publish_run_record(
            tmp_path,
            RunRecordSpec.of(
                "alpha_signal", table_id="alpha.signal", value_fields=("signal", "absent")
            ),
            _result(cutoff),
        )


def test_one_row_per_key_so_stages_must_be_columns(tmp_path: Path) -> None:
    """The shared authority keys on (available_at, instrument) and refuses a duplicate.

    This is why canon fixes several stages of one measurement as distinct columns rather than
    repeated rows: two rows for the same ticker and occurrence would be refused before exposure.
    """
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    duplicated = _Result(
        _State(
            {
                "alpha.signal": (
                    _row(instrument="A", event_time=cutoff, signal="0.5", sequence=0),
                    _row(instrument="A", event_time=cutoff, signal="0.9", sequence=1),
                )
            }
        )
    )

    with pytest.raises(VqaprError):
        publish_run_record(
            tmp_path,
            RunRecordSpec.of("alpha_signal", table_id="alpha.signal", value_fields=("signal",)),
            duplicated,
        )


def test_distinct_occurrences_publish_distinct_rows(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    first = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    second = first + timedelta(days=1)
    across = _Result(
        _State(
            {
                "alpha.signal": (
                    _row(instrument="A", event_time=first, signal="0.5", sequence=0),
                    _row(instrument="A", event_time=second, signal="0.9", sequence=0),
                )
            }
        )
    )

    result = publish_run_record(
        tmp_path,
        RunRecordSpec.of("alpha_signal", table_id="alpha.signal", value_fields=("signal",)),
        across,
    )

    rows = _published(result.output_path)
    assert result.row_count == 2
    assert {str(row[2]) for row in rows} == {"0.5", "0.9"}
    assert Decimal(str(rows[0][2])) < Decimal(str(rows[1][2]))


def test_a_strategy_declaring_the_reserved_prefix_is_refused() -> None:
    """A Strategy cannot shadow a package record.

    Canon 9.2 reserves the prefix at table-id level for the same reason the envelope fields are
    reserved at column level: without it a Strategy could declare `vqapr.account` and hide the
    real one. The guard runs while the recorder is built, before any row is written.
    """
    from vqapr.flow.simulation import DEFAULT_TABLE_PREFIX, SimulationFlow
    from vqapr.public import TableSpec

    # Every spelling below defeated an earlier form of this guard. A plain startswith missed the
    # uppercase and whitespace forms; adding casefold still missed the ones that only NFKC and
    # format-character removal catch. In each case the spoofed table sat beside the real one.
    for spelling in (
        f"{DEFAULT_TABLE_PREFIX}account",
        "VQAPR.account",
        f" {DEFAULT_TABLE_PREFIX}account",
        f"{DEFAULT_TABLE_PREFIX}account_extra",
        "\uff56\uff51\uff41\uff50\uff52\uff0eaccount",
    ):

        class _Shadowing:
            def tables(self, table_id=spelling):
                return (TableSpec(table_id, ("instrument", "cash")),)

        flow = SimulationFlow.__new__(SimulationFlow)
        flow._strategy = _Shadowing()

        with pytest.raises(ValueError, match="package-owned"):
            flow._callback_recorder(object())


def test_the_defaults_need_no_declaration() -> None:
    """Both default tables are package-owned specs, not something a Strategy supplies."""
    from vqapr.flow.simulation import DEFAULT_TABLES

    assert {spec.table_id for spec in DEFAULT_TABLES} == {"vqapr.weight", "vqapr.account"}
    for spec in DEFAULT_TABLES:
        assert "instrument" in spec.fields, "every default row is keyed by instrument"
    # Decision-time state, not a performance series: a callback has no marks, so there is no NAV
    # to copy and none is claimed. Recording cash under the name NAV would be a wrong number under
    # a true-sounding name.
    assert not any("nav" in field for spec in DEFAULT_TABLES for field in spec.fields)


def test_the_namespace_predicate_is_precise_in_both_directions() -> None:
    """The guard must refuse spellings of the reserved prefix without rejecting honest ids.

    An over-broad guard would be the worse defect: rejecting a legitimate Korean or Japanese table
    id to catch a spoof trades a real capability for a hypothetical one.
    """
    from vqapr.flow.simulation import _shadows_package_table

    for spelling in (
        "vqapr.account",
        "VQAPR.account",
        " vqapr.account",
        "vqapr.anything_at_all",
        "\uff56\uff51\uff41\uff50\uff52\uff0eaccount",  # full-width
    ):
        assert _shadows_package_table(spelling), f"{spelling!r} lays claim to the reserved prefix"

    for spelling in (
        "alpha.signal",
        "my.vqapr.audit",
        "reports_vqapr.summary",
        "vqapr_custom.table",
        "\ud559\uc2b5.\uc2e0\ud638",
        "\u30c7\u30fc\u30bf.\u4fe1\u53f7",
    ):
        assert not _shadows_package_table(spelling), f"{spelling!r} is an honest table id"

    # A cross-script lookalike is a documented gap, not a guarantee. Asserted separately so a
    # maintainer who later adds a confusables skeleton reads the failure as the scope changing.
    assert not _shadows_package_table("vq\u0430pr.account"), (
        "cross-script homoglyphs are deliberately out of scope; see the predicate's docstring"
    )


def test_an_invisible_character_cannot_hide_inside_a_table_id() -> None:
    """Closed at construction, not at each consumer.

    A table id is a name a human reads back later, so an invisible codepoint cannot help a reader
    and can only disguise one name as another -- including as a package-owned name. Control and
    format characters are therefore refused where the id is built, which spares every consumer from
    normalising defensively and closes the disguise for names that have nothing to do with the
    reserved namespace.
    """
    for hidden in ("\x00", "\x1b", "\u200b", "\u200d", "\u00ad", "\u2060", "\ufeff"):
        with pytest.raises(ValueError, match="control or format characters"):
            TableSpec(f"{hidden}vqapr.account", ("instrument", "cash"))
        with pytest.raises(ValueError, match="control or format characters"):
            TableSpec(f"alpha{hidden}.signal", ("instrument",))

    # A field name is a name too. A column called `run_id` carrying an invisible character would
    # otherwise pass the reserved-name check and sit beside the real envelope column.
    for hidden in ("\u200b", "\x00"):
        with pytest.raises(ValueError, match="control or format characters"):
            TableSpec("alpha.signal", (f"run_id{hidden}",))

    # Honest ids, including non-Latin ones, are untouched.
    for honest in ("alpha.signal", "\ud559\uc2b5.\uc2e0\ud638", "my.vqapr.audit"):
        TableSpec(honest, ("instrument",))
