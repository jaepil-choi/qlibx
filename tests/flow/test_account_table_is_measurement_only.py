"""`vqapr.account` carries measurements only, so a naive read of it cannot be wrong.

Issue 010. The table had two writers: a valuation occurrence recording what the book was worth,
and a strategy callback recording the account it saw before deciding. The second wrote `nav=None`,
so a consumer reading a NAV series had to know to filter -- and one who forgot paired every real
value with a spurious null. That is the shape `implementations/056` measured as HML correlation
0.9726 -> 0.6877.

What must not be lost is the property 056 bought with its guard: a valuation clock sparser than the
decision clock leaves sessions its own occurrences never reach, and on those the mark a callback
replays is the only record of the book's value there is. That case lives in
`test_valuation_clock.py`; this file pins the shape of the table itself.
"""

from __future__ import annotations

from vqapr.flow.simulation import DEFAULT_TABLE_PREFIX, DEFAULT_TABLES

ACCOUNT = f"{DEFAULT_TABLE_PREFIX}account"


def _spec(table_id: str):
    return next(spec for spec in DEFAULT_TABLES if spec.table_id == table_id)


def test_the_package_owns_exactly_three_default_tables() -> None:
    """A `vqapr.decision_account` briefly stood beside these and was removed.

    It held the cash and positions a callback saw before deciding, on the argument that this is a
    different fact from what the book was worth. Matched on `account_version` its rows were
    identical to this table's -- the same series offset by one commit -- its only unique row was
    the initial account, which `FrozenRun` already carries, and nothing read it. Machinery whose
    only user is its own test is not a feature.
    """
    assert {spec.table_id for spec in DEFAULT_TABLES} == {
        f"{DEFAULT_TABLE_PREFIX}weight",
        ACCOUNT,
        f"{DEFAULT_TABLE_PREFIX}fill",
    }


def test_the_account_table_carries_what_dates_a_measurement() -> None:
    """`observed_at` is when the nav was MEASURED, which is not when the row was written.

    Dating the series by the occurrence instead puts every value one commit late; measured once,
    that mislabelling took a factor correlation from 0.93 to 0.02.
    """
    fields = set(_spec(ACCOUNT).fields)

    assert {"nav", "observed_at", "price"} <= fields


def test_every_default_row_is_keyed_by_instrument() -> None:
    for spec in DEFAULT_TABLES:
        assert "instrument" in spec.fields
