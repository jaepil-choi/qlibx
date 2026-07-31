"""R2 falsifiers for episode-keyed, empirical-preferred last trade dates."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.markets.expiry import days_to_last_trade, empirical_last_trade
from echolon.markets.shfe.trading_calendar import TradingCalendar


def test_rm601_resolves_distinct_decade_episodes() -> None:
    assert empirical_last_trade("RM601", dt.date(2016, 1, 10)) == dt.date(2016, 1, 15)
    assert empirical_last_trade("RM601", dt.date(2026, 1, 10)) == dt.date(2026, 1, 14)


def test_empirical_lookup_uses_nearest_episode_before_asof() -> None:
    assert empirical_last_trade("RM601", dt.date(2020, 1, 1)) == dt.date(2016, 1, 15)


def test_days_to_last_trade_prefers_expired_eg_episode() -> None:
    calendar = _business_calendar("2024-07-01", "2024-07-31")
    # EG2407 empirically stopped on July 19; its encoded boundary is July 26.
    assert days_to_last_trade("EG2407", "DCE", dt.date(2024, 7, 15), calendar) == 4


def test_days_to_last_trade_prefers_expired_czce_episode() -> None:
    calendar = _business_calendar("2026-01-01", "2026-01-31")
    assert days_to_last_trade("RM601", "CZCE", dt.date(2026, 1, 8), calendar) == 4


def test_live_dce_contract_still_uses_encoded_rule() -> None:
    calendar = _business_calendar("2026-09-01", "2026-09-30")
    assert days_to_last_trade("M2609", "DCE", dt.date(2026, 9, 7), calendar) == 5


def test_empirical_resolution_rejects_unloaded_calendar_and_wrong_exchange() -> None:
    with pytest.raises(ValueError, match="loaded exchange calendar"):
        days_to_last_trade("EG2407", "DCE", dt.date(2024, 7, 15), TradingCalendar())
    calendar = _business_calendar("2024-07-01", "2024-07-31")
    with pytest.raises(ValueError, match="belongs to DCE"):
        days_to_last_trade("EG2407", "CZCE", dt.date(2024, 7, 15), calendar)


def _business_calendar(start: str, end: str) -> TradingCalendar:
    calendar = TradingCalendar()
    calendar._trading_days = {value.date() for value in pd.bdate_range(start, end)}
    calendar._calendar_loaded = True
    return calendar
