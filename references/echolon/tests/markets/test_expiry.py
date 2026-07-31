"""Exchange-true futures last-trade and position-close falsifiers."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.markets.expiry import (
    days_to_expiry,
    days_to_last_trade,
    days_to_position_close,
    expiry_date,
    last_trade_date,
    position_close_date,
)
from echolon.markets.shfe.trading_calendar import TradingCalendar


@pytest.fixture
def pinned_shfe_calendar(tmp_path) -> TradingCalendar:
    # The plan defines SHFE "expiry" as the last date a general position may be
    # held before delivery month and mandates delegation to contract_rules.py.
    # Rule source: echolon/markets/shfe/contract_rules.py:get_expiry_date, which
    # is the authoritative in-repo source explicitly pinned by FV2-WP2a D2.
    # These five dates were independently checked against the SHFE sessions in
    # the p2_v4 snapshot (the expected month-end sessions are listed below).
    trading_days = pd.to_datetime(
        [
            "2024-01-31",  # al2402
            "2024-02-29",  # cu2403
            "2024-04-30",  # rb2405
            "2024-09-30",  # zn2410
            "2025-01-27",  # ni2502; Jan 28-31 exchange holiday
            "2025-02-05",
            "2025-02-06",
            "2025-02-07",
            "2025-02-10",
        ]
    )
    path = tmp_path / "shfe_calendar.csv"
    pd.DataFrame({"date": trading_days.strftime("%Y-%m-%d")}).to_csv(path, index=False)
    return TradingCalendar(str(path))


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        ("al2402", dt.date(2024, 1, 31)),
        ("CU2403", dt.date(2024, 2, 29)),
        ("rb2405", dt.date(2024, 4, 30)),
        ("zn2410", dt.date(2024, 9, 30)),
        ("ni2502", dt.date(2025, 1, 27)),
    ],
)
def test_shfe_expiry_delegates_to_pinned_contract_rule(
    pinned_shfe_calendar: TradingCalendar,
    contract: str,
    expected: dt.date,
) -> None:
    assert expiry_date(contract, "shfe", pinned_shfe_calendar) == expected


def test_expiry_rejects_unloaded_weekend_only_calendar() -> None:
    with pytest.raises(ValueError, match="loaded exchange calendar"):
        expiry_date("cu2403", "SHFE", TradingCalendar())


@pytest.mark.parametrize("exchange", ["CZCE", "DCE", "INE", "UNKNOWN"])
def test_expiry_fails_loudly_for_unpinned_exchange(exchange: str) -> None:
    with pytest.raises(NotImplementedError, match=exchange):
        expiry_date("cu2403", exchange, object())


def test_days_to_expiry_counts_future_trading_sessions_only(
    pinned_shfe_calendar: TradingCalendar,
) -> None:
    assert (
        days_to_expiry(
            "ni2503",
            "SHFE",
            dt.date(2025, 2, 5),
            pinned_shfe_calendar,
        )
        == 3
    )
    assert (
        days_to_expiry(
            "ni2503",
            "SHFE",
            dt.date(2025, 2, 10),
            pinned_shfe_calendar,
        )
        == 0
    )


def test_shfe_last_trade_and_position_close_are_distinct(
    pinned_shfe_calendar: TradingCalendar,
) -> None:
    assert position_close_date("ni2503", "SHFE", pinned_shfe_calendar) == dt.date(
        2025, 2, 10
    )
    assert last_trade_date("ni2502", "SHFE", pinned_shfe_calendar) == dt.date(
        2025, 2, 10
    )
    assert (
        days_to_position_close(
            "ni2503", "SHFE", dt.date(2025, 2, 5), pinned_shfe_calendar
        )
        == 3
    )


def test_dce_tenth_trading_day_convention() -> None:
    calendar = _calendar(
        "2024-03-01",
        "2024-03-04",
        "2024-03-05",
        "2024-03-06",
        "2024-03-07",
        "2024-03-08",
        "2024-03-11",
        "2024-03-12",
        "2024-03-13",
        "2024-03-14",
        "2024-03-15",
        "2024-03-18",
        "2024-03-19",
        "2024-03-20",
        "2024-03-21",
        "2024-03-22",
        "2024-03-25",
        "2024-03-26",
        "2024-03-27",
        "2024-03-28",
        "2024-03-29",
    )
    assert last_trade_date("M2403", "DCE", calendar) == dt.date(2024, 3, 14)
    assert days_to_last_trade("M2403", "DCE", dt.date(2024, 3, 11), calendar) == 3
    assert (
        days_to_position_close("M2403", "DCE", dt.date(2024, 3, 11), calendar) is None
    )


@pytest.mark.parametrize("contract", ["EG2403", "JD2403"])
def test_dce_eg_and_jd_fourth_from_month_end_convention(contract: str) -> None:
    calendar = _calendar(
        "2024-03-01",
        "2024-03-04",
        "2024-03-05",
        "2024-03-06",
        "2024-03-07",
        "2024-03-08",
        "2024-03-11",
        "2024-03-12",
        "2024-03-13",
        "2024-03-14",
        "2024-03-15",
        "2024-03-18",
        "2024-03-19",
        "2024-03-20",
        "2024-03-21",
        "2024-03-22",
        "2024-03-25",
        "2024-03-26",
        "2024-03-27",
        "2024-03-28",
        "2024-03-29",
    )
    assert last_trade_date(contract, "DCE", calendar) == dt.date(2024, 3, 26)


def test_new_last_trade_api_keeps_ine_descoped() -> None:
    with pytest.raises(NotImplementedError, match="INE"):
        last_trade_date("SC2403", "INE", object())


def test_czce_position_close_is_explicitly_undefined() -> None:
    calendar = _calendar("2026-01-08")
    assert (
        days_to_position_close("RM601", "CZCE", dt.date(2026, 1, 8), calendar) is None
    )


def _calendar(*dates: str) -> TradingCalendar:
    calendar = TradingCalendar()
    calendar._trading_days = {dt.date.fromisoformat(value) for value in dates}
    calendar._calendar_loaded = True
    return calendar
