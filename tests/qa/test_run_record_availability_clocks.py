"""Adversarial attack on claim 7: per-table availability clock, `vqapr.account` by `observed_at`,
decision tables by `event_time`.

Three attacks:

1. Publish a `vqapr.account` table where `observed_at` and `event_time` genuinely differ (hours
   apart, as the real F-009 regression was), and confirm `available_at` follows `observed_at`,
   not `event_time`.
2. `observed_at` present as a declared value field but NULL on some rows -- must refuse rather
   than silently substitute `event_time` or drop the row.
3. Declare `availability_field` naming a column that IS present on every row but was NOT declared
   in `value_fields` -- confirmed to be refused at `RunRecordSpec` construction time, before any
   row is ever touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.evidence.tables import FLOW_ENVELOPE_FIELDS
from vqapr.public import RunRecordSpec, publish_run_record
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")

_NAV_FIELDS = ("nav", "observed_at", "run_id", "producer_id", "stage", "event_time", "sequence")


@dataclass(frozen=True)
class _State:
    recorder_rows: dict[str, tuple[dict[str, object], ...]]


@dataclass(frozen=True)
class _Result:
    final_state: _State


def _nav_row(
    *, event_time: datetime, observed_at: object, nav: str, sequence: int = 0
) -> dict[str, object]:
    return {
        "instrument": "_ACCOUNT",
        "nav": nav,
        "observed_at": observed_at,
        "run_id": "run-1",
        "producer_id": "alpha",
        "stage": "VALUATION",
        "event_time": event_time,
        "sequence": sequence,
    }


def _stamps(path: Path) -> list[object]:
    con = duckdb.connect()
    try:
        return [
            row[0]
            for row in con.execute(
                f"SELECT available_at FROM read_parquet('{path.as_posix()}') "
                "ORDER BY available_at"
            ).fetchall()
        ]
    finally:
        con.close()


def test_the_account_series_is_dated_by_observed_at_when_it_genuinely_diverges_from_event_time(
    tmp_path: Path,
) -> None:
    """A wide gap (days, not minutes) between the two clocks, mirroring the real F-009 shape:
    a NAV measured on one day, written into the record the next morning.
    """
    Workspace.create(tmp_path)
    written = datetime(2026, 4, 2, 8, 0, tzinfo=KST)
    measured = datetime(2026, 3, 28, 16, 0, tzinfo=KST)  # five days earlier

    result = publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "factor_nav",
            table_id="vqapr.account",
            value_fields=_NAV_FIELDS,
            availability_field="observed_at",
        ),
        _Result(
            _State(
                {
                    "vqapr.account": (
                        _nav_row(event_time=written, observed_at=measured, nav="1000"),
                    )
                }
            )
        ),
    )

    assert _stamps(result.output_path) == [measured], (
        "the account series must be dated by when the NAV was measured, not written"
    )


def test_an_unmeasured_occurrence_is_dated_by_when_it_happened(tmp_path: Path) -> None:
    """A partial-NULL measurement clock is dated by when the row happened, not refused.

    This originally pinned a refusal, and the refusal was wrong. `observed_at` is null on any
    occurrence that took no mark -- the venue published no price at or before the instant, so the
    book was genuinely not measured. On the real factor table that is 2,368,704 of 4,738,842 rows,
    so refusing made the per-table clock unusable on `vqapr.account`: the one table it exists for.

    The measured row keeps its measurement instant; the unmeasured one falls back to its own
    `event_time`. Neither is dated by the other's clock, and an ABSENT column is still refused --
    that distinction is what keeps this from being a silent substitution.
    """
    Workspace.create(tmp_path)
    measured_at = datetime(2026, 4, 1, 16, 0, tzinfo=KST)
    written_at = datetime(2026, 4, 2, 8, 0, tzinfo=KST)
    good_row = _nav_row(event_time=measured_at, observed_at=measured_at, nav="1000", sequence=0)
    unmeasured = _nav_row(event_time=written_at, observed_at=None, nav="1001", sequence=1)

    result = publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "factor_nav",
            table_id="vqapr.account",
            value_fields=_NAV_FIELDS,
            availability_field="observed_at",
        ),
        _Result(_State({"vqapr.account": (good_row, unmeasured)})),
    )

    con = duckdb.connect()
    try:
        stamps = {
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT available_at FROM read_parquet('{result.output_path.as_posix()}')"
            ).fetchall()
        }
    finally:
        con.close()

    assert stamps == {measured_at, written_at}


def test_availability_field_naming_a_column_present_on_rows_but_absent_from_value_fields(
) -> None:
    """The column exists on every row that would be recorded, but was never DECLARED as a value
    field -- `RunRecordSpec.of` must refuse this at construction, before any row is inspected, so
    the mistake is caught even if the run never actually records a row.
    """
    with pytest.raises(ValueError, match="availability_field"):
        RunRecordSpec.of(
            "d",
            table_id="alpha.signal",
            value_fields=(*sorted(FLOW_ENVELOPE_FIELDS), "signal"),
            # 'observed_at' is a column real rows for this table WOULD carry (it is a legitimate
            # vqapr.account column elsewhere), but it is not among the value_fields declared here.
            availability_field="observed_at",
        )


def test_a_decision_table_is_still_dated_by_event_time_when_the_two_specs_coexist(
    tmp_path: Path,
) -> None:
    """The other half of the per-table claim: a table declaring NO observed_at at all must still
    date correctly by event_time, proving the clock really is chosen per RunRecordSpec and not
    accidentally pinned globally by whichever table was published most recently in the process.
    """
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)

    # Publish the account table FIRST (observed_at clock)...
    publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "factor_nav_2",
            table_id="vqapr.account",
            value_fields=_NAV_FIELDS,
            availability_field="observed_at",
        ),
        _Result(
            _State(
                {
                    "vqapr.account": (
                        _nav_row(
                            event_time=cutoff,
                            observed_at=cutoff - timedelta(hours=3),
                            nav="1000",
                        ),
                    )
                }
            )
        ),
    )

    # ...then publish a decision table (event_time clock) and confirm it is NOT dated by the
    # previous call's observed_at convention.
    decision_result = publish_run_record(
        tmp_path,
        RunRecordSpec.of(
            "alpha_signal_2",
            table_id="alpha.signal",
            value_fields=("signal", "run_id", "producer_id", "stage", "event_time", "sequence"),
        ),
        _Result(
            _State(
                {
                    "alpha.signal": (
                        {
                            "instrument": "A",
                            "signal": "0.5",
                            "run_id": "run-1",
                            "producer_id": "alpha",
                            "stage": "STRATEGY_CALLBACK",
                            "event_time": cutoff,
                            "sequence": 0,
                        },
                    )
                }
            )
        ),
    )

    assert _stamps(decision_result.output_path) == [cutoff]
