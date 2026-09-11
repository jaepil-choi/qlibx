"""`every` / `from` / `to` / `at`: the strategy clock as arithmetic over trading days.

Design §3.3-3.4 (record `204`). The declaration is a trading-day filter plus a within-day rule;
the trading days are handed in from data, and `AgendaRule`/`OperationAgenda.expand` do only
arithmetic on top -- so nothing here guesses a market fact. `UC-TIME-002`'s guarantee lives in
the first test: a 1-minute table and a daily table carry the same DAYS, so they expand to the
same agenda.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from vqapr.domain.identifiers import agenda_id
from vqapr.domain.schedule import AgendaRule, OperationAgenda

SEOUL = "Asia/Seoul"
JANUARY = tuple(
    day
    for day in (date(2024, 1, 1) + timedelta(days=n) for n in range(31))
    if day.weekday() < 5
)
"""The 23 weekdays of January 2024: a trading-day set with two partial weeks and one month."""


def _expand(rule: AgendaRule, days=JANUARY, timezone: str = SEOUL) -> OperationAgenda:
    return OperationAgenda.expand(agenda_id=agenda_id("r"), days=days, rule=rule, timezone=timezone)


def test_a_denser_execution_table_adds_no_decision_day() -> None:
    """`UC-TIME-002`: the days are what count, and both tables have the same days."""
    zone = ZoneInfo(SEOUL)
    daily = [datetime.combine(day, time(15, 30), tzinfo=zone) for day in JANUARY[:3]]
    minutes = [
        datetime.combine(day, time(9, 0), tzinfo=zone) + timedelta(minutes=k)
        for day in JANUARY[:3]
        for k in range(0, 390)
    ]
    rule = AgendaRule("1d", (time(9, 0),))

    assert _expand(rule, minutes).content_identity == _expand(rule, daily).content_identity
    assert len(_expand(rule, minutes).occurrences) == 3


def test_every_nth_trading_day_counts_trading_days_not_calendar_days() -> None:
    every_other = _expand(AgendaRule("2d", (time(9),)))
    assert [o.local_instant.local_date for o in every_other.occurrences] == list(JANUARY[::2])
    # A holiday removed from the table shifts the count, because it is not a trading day.
    without = tuple(day for day in JANUARY if day != date(2024, 1, 3))
    shifted = _expand(AgendaRule("2d", (time(9),)), without)
    assert [o.local_instant.local_date for o in shifted.occurrences] == list(without[::2])


def test_weekly_and_monthly_fire_on_the_first_trading_day_of_the_group() -> None:
    weekly = _expand(AgendaRule("1w", (time(9),)))
    assert [o.local_instant.local_date for o in weekly.occurrences] == [
        date(2024, 1, 1),
        date(2024, 1, 8),
        date(2024, 1, 15),
        date(2024, 1, 22),
        date(2024, 1, 29),
    ]
    # Monday the 1st is a holiday: the first TRADING day of that week and month is the 2nd.
    without_new_year = tuple(day for day in JANUARY if day != date(2024, 1, 1))
    monthly = _expand(AgendaRule("1M", (time(9),)), without_new_year)
    assert [o.local_instant.local_date for o in monthly.occurrences] == [date(2024, 1, 2)]
    fortnightly = _expand(AgendaRule("2w", (time(9),)))
    assert [o.local_instant.local_date for o in fortnightly.occurrences] == [
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 1, 29),
    ]


FEBRUARY_OPENING = (date(2024, 2, 1), date(2024, 2, 2), date(2024, 2, 5))
"""The first three sessions of February 2024: Thursday, Friday and the next Monday."""


def _dates(agenda: OperationAgenda) -> list[date]:
    return [o.local_instant.local_date for o in agenda.occurrences]


def test_on_last_fires_on_the_last_trading_day_of_each_group_the_days_show_over() -> None:
    """`docs/issues/report-2026-09-11-an-agenda-cannot-fire-on-the-last-trading-day-of-a-month.md`.

    Record `253`. January is over because February's sessions follow it; February is not -- the
    days stop on the 5th -- so it does not fire, rather than firing on a day that may not be its
    last. The ISO week of Monday the 29th runs to Friday 2 February.
    """
    days = JANUARY + FEBRUARY_OPENING
    assert _dates(_expand(AgendaRule("1M", (time(15, 20),), on="last"), days)) == [
        date(2024, 1, 31)
    ]
    assert _dates(_expand(AgendaRule("1w", (time(15, 20),), on="last"), days)) == [
        date(2024, 1, 5),
        date(2024, 1, 12),
        date(2024, 1, 19),
        date(2024, 1, 26),
        date(2024, 2, 2),
    ]
    # A holiday on the 31st makes the 30th the month's last trading day.
    without = tuple(day for day in days if day != date(2024, 1, 31))
    assert _dates(_expand(AgendaRule("1M", (time(15, 20),), on="last"), without)) == [
        date(2024, 1, 30)
    ]


def test_a_month_is_over_when_no_calendar_day_of_it_is_left() -> None:
    """Days that stop on the month's last calendar day need no later session to end it; days
    that stop on Friday the 26th say nothing about the 29th to the 31st."""
    rule = AgendaRule("1M", (time(15, 20),), on="last")
    assert _dates(_expand(rule, JANUARY)) == [date(2024, 1, 31)]
    assert _dates(_expand(rule, JANUARY[:-3])) == []


def test_through_keeps_the_days_fired_on_or_before_it() -> None:
    """How a run hands `on: last` the days past its `end` and fires on none of them."""
    agenda = OperationAgenda.expand(
        agenda_id=agenda_id("r"),
        days=JANUARY + FEBRUARY_OPENING,
        rule=AgendaRule("1w", (time(9),), on="last"),
        timezone=SEOUL,
        through=date(2024, 1, 20),
    )
    assert _dates(agenda) == [date(2024, 1, 5), date(2024, 1, 12), date(2024, 1, 19)]


def test_several_wall_times_a_day_are_several_occurrences_in_order() -> None:
    agenda = _expand(AgendaRule("1d", (time(15, 0), time(9, 0))), JANUARY[:1])
    assert [o.occurrence_id for o in agenda.occurrences] == [
        "r-2024-01-01T0900",
        "r-2024-01-01T1500",
    ]


def test_an_intraday_rule_walks_the_window_inclusively_on_every_trading_day() -> None:
    """`every: 5m from 09:00 to 09:10` is three instants a day, on each day the table has."""
    rule = AgendaRule("5m", from_time=time(9, 0), to_time=time(9, 10))
    assert rule.times() == (time(9, 0), time(9, 5), time(9, 10))
    agenda = _expand(rule, JANUARY[:2])
    assert len(agenda.occurrences) == 6
    assert agenda.occurrences[0].evaluation_time.isoformat() == "2024-01-01T09:00:00+09:00"
    assert agenda.occurrences[-1].evaluation_time.isoformat() == "2024-01-02T09:10:00+09:00"
    hourly = AgendaRule("1h", from_time=time(9), to_time=time(15, 30))
    assert [t.hour for t in hourly.times()] == [9, 10, 11, 12, 13, 14, 15]


def test_a_minute_grid_over_a_year_expands() -> None:
    """The size the design names: 250 days x 390 minutes = 97,500 occurrences."""
    days = tuple(date(2023, 1, 2) + timedelta(days=n) for n in range(250))
    rule = AgendaRule("1m", from_time=time(9, 0), to_time=time(15, 29))
    assert len(rule.times()) == 390
    assert len(_expand(rule, days).occurrences) == 97_500


@pytest.mark.parametrize(
    ("kwargs", "said"),
    [
        ({"every": "daily", "at": (time(9),)}, "count and a unit"),
        ({"every": "0d", "at": (time(9),)}, "count and a unit"),
        # The refusal states the grammar (the count is free; the units are d, w, M and m, h) and
        # a year unit points at the spelling that exists.
        ({"every": "1y", "at": (time(9),)}, "a yearly cadence is 12M"),
        ({"every": "1Y", "at": (time(9),)}, "any positive integer.*d, w or M.*12M"),
        ({"every": "1d"}, "needs at"),
        ({"every": "1d", "at": (time(9), time(9))}, "must not repeat"),
        ({"every": "1d", "at": (time(9),), "from_time": time(9)}, "declare at, not from/to"),
        ({"every": "5m", "at": (time(9),)}, "declare from/to, not at"),
        ({"every": "5m", "from_time": time(9)}, "needs from and to"),
        ({"every": "5m", "from_time": time(10), "to_time": time(9)}, "from must not be later"),
        ({"every": "1d", "at": (time(9, tzinfo=UTC),)}, "timezone-naive"),
        # `on` names a day of a week or a month, so a rule with neither has nothing to be last in.
        ({"every": "1d", "at": (time(9),), "on": "last"}, "pairs with a w or M rule"),
        ({"every": "1M", "at": (time(9),), "on": "middle"}, "on is first or last"),
    ],
)
def test_a_rule_whose_halves_disagree_is_refused_by_name(kwargs: dict, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        AgendaRule(**kwargs)


def test_the_rule_describes_itself_the_way_the_declaration_reads() -> None:
    assert AgendaRule("1M", (time(9, 30),)).describe() == "every 1M at 09:30:00"
    assert (
        AgendaRule("1M", (time(15, 29),), on="last").describe()
        == "every 1M on the last trading day at 15:29:00"
    )
    assert (
        AgendaRule("5m", from_time=time(9), to_time=time(15, 20)).describe()
        == "every 5m from 09:00:00 to 15:20:00 on each trading day"
    )
