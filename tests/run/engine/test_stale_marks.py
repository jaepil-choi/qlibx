"""A holding the venue stopped quoting keeps its last price, and says how old it is.

The mechanism changed and the contract did not. Marks used to come from an observation
subscription that searched history for the newest row at or before the cutoff. They now come from
the execution snapshot the run fills against, and a name the venue published nothing for carries
its previous mark forward. Both answers are the same for a halted holding: **it keeps its last
real price, and it says when that price was observed.**

Writing a halted position down to nothing would report a loss that did not happen. Dropping it
would lose the position. Re-stamping its `observed_at` with the current instant would hide the
halt. None of those are acceptable, so all three are pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from vqapr.data.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.domain.account import AccountMark, Mark, MarkBatch
from vqapr.domain.valuation import SelectedMark, select_prices

QUOTED = datetime(2024, 1, 4, 6, 30, tzinfo=UTC)
"""The last instant the venue published a price for the halted name."""

LATER = datetime(2024, 1, 10, 6, 30, tzinfo=UTC)
"""Six days later. The halted name has no row here."""


def _snapshot(target_at: datetime, *rows: ExactExecutionRow) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(
        target_at=target_at,
        rows=rows,
        duplicate_instruments=(),
        missing_target_instruments=(),
        missing_held_instruments=(),
    )


def _previous_mark(*, price: str, observed_at: datetime) -> AccountMark:
    mark = Mark("HALT", Decimal("5"), Decimal(price), Decimal("5") * Decimal(price))
    return AccountMark(
        account_version=1,
        marks=MarkBatch((mark,), mark.value),
        nav=Decimal("1000") + mark.value,
        marked_at=QUOTED,
        observed_at_by_instrument={"HALT": observed_at},
    )


def _by_instrument(marks: tuple[SelectedMark, ...]) -> dict[str, SelectedMark]:
    return {mark.instrument_id: mark for mark in marks}


def test_a_holding_that_stopped_quoting_keeps_its_last_price() -> None:
    """Writing a halted position down to nothing would report a loss that did not happen."""
    marks = _by_instrument(
        select_prices(
            _snapshot(LATER, ExactExecutionRow(LATER, "LIVE", True, Decimal("109"))),
            LATER,
            previous=_previous_mark(price="203", observed_at=QUOTED),
            held={"LIVE": Decimal("10"), "HALT": Decimal("5")},
        )
    )

    assert marks["HALT"].price == Decimal("203")
    assert marks["LIVE"].price == Decimal("109")


def test_each_mark_reports_how_old_its_price_is() -> None:
    """Valuation states the observation instant; it does not decide what the gap means.

    A long halt and a delisting are identical at the cutoff and are told apart only by whether
    the instrument trades again, which is a fact from the future.
    """
    marks = _by_instrument(
        select_prices(
            _snapshot(LATER, ExactExecutionRow(LATER, "LIVE", True, Decimal("109"))),
            LATER,
            previous=_previous_mark(price="203", observed_at=QUOTED),
            held={"LIVE": Decimal("10"), "HALT": Decimal("5")},
        )
    )

    assert marks["LIVE"].staleness(LATER) == timedelta(0)
    assert marks["HALT"].staleness(LATER) == timedelta(days=6)


def test_carrying_a_mark_forward_does_not_restamp_when_it_was_observed() -> None:
    """The gap has to survive being carried.

    If a carried mark took the current instant as its own, a name halted for a year would look
    freshly priced at every event and the halt would be invisible in the evidence.
    """
    once = select_prices(
        _snapshot(LATER),
        LATER,
        previous=_previous_mark(price="203", observed_at=QUOTED),
        held={"HALT": Decimal("5")},
    )
    twice = select_prices(
        _snapshot(LATER + timedelta(days=30)),
        LATER + timedelta(days=30),
        previous=AccountMark(
            account_version=1,
            marks=MarkBatch(
                (Mark("HALT", Decimal("5"), Decimal("203"), Decimal("1015")),), Decimal("1015")
            ),
            nav=Decimal("2015"),
            marked_at=LATER,
            observed_at_by_instrument={"HALT": once[0].observed_at},
        ),
        held={"HALT": Decimal("5")},
    )

    assert once[0].observed_at == QUOTED
    assert twice[0].observed_at == QUOTED


def test_a_venue_price_wins_over_a_carried_one() -> None:
    """A carried mark is a fallback, never a preference. Trading resumes and the price moves."""
    marks = _by_instrument(
        select_prices(
            _snapshot(LATER, ExactExecutionRow(LATER, "HALT", True, Decimal("250"))),
            LATER,
            previous=_previous_mark(price="203", observed_at=QUOTED),
            held={"HALT": Decimal("5")},
        )
    )

    assert marks["HALT"].price == Decimal("250")
    assert marks["HALT"].observed_at == LATER


def test_a_name_the_venue_will_not_trade_is_still_priced_by_it() -> None:
    """Refusing to trade and refusing to quote are different facts.

    `is_tradable=false` stops a fill. It does not stop a valuation: the venue published a price,
    and that price is the best statement of what the holding is worth.
    """
    marks = _by_instrument(
        select_prices(
            _snapshot(LATER, ExactExecutionRow(LATER, "HALT", False, Decimal("190"))),
            LATER,
            previous=_previous_mark(price="203", observed_at=QUOTED),
            held={"HALT": Decimal("5")},
        )
    )

    assert marks["HALT"].price == Decimal("190")
    assert marks["HALT"].observed_at == LATER


def test_a_holding_that_was_never_priced_produces_no_mark() -> None:
    """An opening position the venue has never priced has no honest number to contribute.

    It is left out of NAV rather than refused, and it keeps its quantity in the account.
    """
    marks = select_prices(
        _snapshot(LATER),
        LATER,
        previous=None,
        held={"NEVER": Decimal("5")},
    )

    assert marks == ()


def test_a_sold_holding_is_not_carried_back_into_the_book() -> None:
    """Carry-forward follows the account, not the previous mark.

    A name that is no longer held must not reappear in NAV because an older mark mentioned it.
    """
    marks = select_prices(
        _snapshot(LATER),
        LATER,
        previous=_previous_mark(price="203", observed_at=QUOTED),
        held={},
    )

    assert marks == ()


def test_a_mark_requires_a_timezone_aware_observation() -> None:
    with pytest.raises(ValueError, match="observed_at"):
        SelectedMark("A", Decimal("10"), datetime(2024, 1, 1, 6, 30))
