"""`vqapr.account` carries measurements only, so a naive read of it cannot be wrong.

Issue 010. The table had two writers: a valuation occurrence recording what the book was worth,
and a strategy callback recording what the account looked like when a decision was made. The
second wrote `nav=None`, so a consumer reading a NAV series had to know to filter -- and one who
forgot paired every real value with a spurious null. That is the shape `implementations/056`
measured as HML correlation 0.9726 -> 0.6877.

The fix separated the two FACTS rather than the two writers. What must not be lost is the property
056 bought with its guard: a valuation clock sparser than the decision clock leaves sessions its
own occurrences never reach, and on those the callback's replayed mark is the only record there
is. That case is covered in `test_valuation_clock.py`; this file pins the shape of the table.
"""

from __future__ import annotations

from vqapr.flow.simulation import DEFAULT_TABLE_PREFIX, DEFAULT_TABLES

ACCOUNT = f"{DEFAULT_TABLE_PREFIX}account"
DECISION_ACCOUNT = f"{DEFAULT_TABLE_PREFIX}decision_account"


def _spec(table_id: str):
    return next(spec for spec in DEFAULT_TABLES if spec.table_id == table_id)


def test_the_decision_time_account_is_its_own_default_table() -> None:
    """Named for the question it answers, rather than sharing one that answers another."""
    assert {spec.table_id for spec in DEFAULT_TABLES} == {
        f"{DEFAULT_TABLE_PREFIX}weight",
        ACCOUNT,
        DECISION_ACCOUNT,
        f"{DEFAULT_TABLE_PREFIX}fill",
    }


def test_the_decision_table_carries_no_measurement_columns() -> None:
    """`nav`, `price` and `observed_at` are absent, deliberately.

    They answer "what was this worth, and when was that measured", and nothing on this path
    measures anything -- it reports the positions a callback saw before deciding. Carrying them
    would invite a reader to date a series by a column that is structurally empty, which is the
    defect this issue removed in its other direction.
    """
    fields = set(_spec(DECISION_ACCOUNT).fields)

    assert fields == {"instrument", "cash", "quantity", "account_version"}
    for measurement in ("nav", "price", "observed_at"):
        assert measurement not in fields, (
            f"{measurement!r} is a measurement column; this table records a decision-time fact"
        )


def test_the_account_table_still_carries_what_dates_a_measurement() -> None:
    """The other half: `vqapr.account` keeps the columns a NAV series is read by.

    `observed_at` is when the nav was MEASURED, which is not when the row was written. Dating the
    series by the occurrence instead puts every value one commit late; measured once, that
    mislabelling took a factor correlation from 0.93 to 0.02.
    """
    fields = set(_spec(ACCOUNT).fields)

    assert {"nav", "observed_at", "price"} <= fields


def test_every_default_row_is_keyed_by_instrument() -> None:
    """Including the new one, which uses the same synthetic account-level identity."""
    for spec in DEFAULT_TABLES:
        assert "instrument" in spec.fields
