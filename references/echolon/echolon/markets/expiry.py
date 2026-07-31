"""Exchange-backed futures last-trade and position-close utilities.

``days_to_last_trade`` prefers episode-empirical dates for every expired
contract available in the bundled panel table. Encoded conventions are used
only when no expired episode is available. This matters especially for DCE EG,
where 22 of 46 R1 rule divergences ended empirically before the formal boundary.
CZCE's candidate convention failed its episode-keyed validation bar and is
therefore available for falsification only, never as an operational fallback.
GFEX has no encoded convention at all: its last-trade support is bundled
empirical episodes only (``days_to_last_trade`` serves expired GFEX contracts
and refuses beyond-data ones), never a guessed rule.
"""

from __future__ import annotations

import calendar as month_calendar
import datetime as dt
import re

from echolon.markets.shfe import contract_rules as shfe_contract_rules
from echolon.markets.shfe.trading_calendar import TradingCalendar
from echolon.markets.empirical_expiry import empirical_episode
from echolon.markets.empirical_expiry import (
    empirical_last_trade as empirical_last_trade,
)


def _require_loaded_calendar(calendar: TradingCalendar) -> None:
    """Reject the SHFE calendar's weekend-only approximation mode."""
    if not isinstance(calendar, TradingCalendar) or not calendar.is_loaded:
        raise ValueError("expiry calculation requires a loaded exchange calendar")


def last_trade_date(
    contract: str,
    exchange: str,
    calendar: TradingCalendar,
) -> dt.date:
    """Return the final trading date, requiring a loaded exchange calendar.

    Supported encoded conventions are SHFE's trading day on or before the
    delivery-month 15th and DCE's delivery-month tenth trading day, except
    DCE EG/JD whose convention is the fourth trading day from month end.
    These are encoded conventions, not claims of an external citation.
    Unsupported exchanges fail with :class:`NotImplementedError`.
    """
    exchange_id = exchange.upper()
    if exchange_id == "CZCE":
        raise NotImplementedError(
            "CZCE encoded last-trade rule failed empirical validation; "
            "expired episodes are empirical-only"
        )
    if exchange_id == "GFEX":
        raise NotImplementedError(
            "GFEX has no encoded last-trade rule and none is guessed; expired "
            "episodes are empirical-only. days_to_last_trade serves bundled "
            "GFEX episodes and refuses beyond-data contracts by design"
        )
    return encoded_last_trade_date(contract, exchange_id, calendar)


def encoded_last_trade_date(
    contract: str,
    exchange: str,
    calendar: TradingCalendar,
    *,
    delivery_year: int | None = None,
) -> dt.date:
    """Return an encoded convention date, including failed-rule candidates.

    The CZCE tenth-trading-day candidate is exposed only so its sub-95% result
    remains reproducible. Operational callers use :func:`last_trade_date`,
    which refuses CZCE rule fallback. ``delivery_year`` is mandatory for CZCE
    because its three-digit identifiers repeat every decade.
    """
    exchange_id = exchange.upper()
    if exchange_id not in {"SHFE", "DCE", "CZCE"}:
        raise NotImplementedError(
            f"{exchange_id} last-trade rule is not authoritatively pinned"
        )
    _require_loaded_calendar(calendar)
    if exchange_id == "CZCE":
        year_digit, product, month = _parse_three_digit_contract(contract)
        if delivery_year is None or delivery_year % 10 != year_digit:
            raise ValueError(
                "CZCE delivery_year must match the contract's repeating year digit"
            )
        year = delivery_year
    else:
        product, year, month = _parse_four_digit_contract(contract)
    trading_days = _trading_days_in_month(calendar, year, month)
    if exchange_id == "SHFE":
        eligible = [day for day in trading_days if day.day <= 15]
        if not eligible:
            raise ValueError(
                f"calendar has no SHFE sessions through {year}-{month:02d}-15"
            )
        return eligible[-1]
    if exchange_id == "DCE" and product in {"eg", "jd"}:
        if len(trading_days) < 4:
            raise ValueError(
                f"calendar has fewer than four DCE sessions in {year}-{month:02d}"
            )
        return trading_days[-4]
    if len(trading_days) < 10:
        raise ValueError(
            f"calendar has fewer than ten {exchange_id} sessions in {year}-{month:02d}"
        )
    return trading_days[9]


def position_close_date(
    contract: str,
    exchange: str,
    calendar: TradingCalendar,
) -> dt.date | None:
    """Return the final general-position holding date, or ``None`` if undefined.

    The in-repository SHFE rule defines this separately from last trade. DCE
    and CZCE have no encoded position-close convention here and are never
    guessed.
    """
    exchange_id = exchange.upper()
    if exchange_id == "SHFE":
        _require_loaded_calendar(calendar)
        return shfe_contract_rules.get_expiry_date(contract, calendar)
    if exchange_id in {"DCE", "CZCE"}:
        _require_loaded_calendar(calendar)
        return None
    raise NotImplementedError(
        f"{exchange_id} position-close rule is not authoritatively pinned"
    )


def days_to_last_trade(
    contract: str,
    exchange: str,
    asof: dt.date,
    calendar: TradingCalendar,
) -> int:
    """Return signed sessions to empirical-preferred last trade."""
    _require_loaded_calendar(calendar)
    episode = empirical_episode(contract, asof)
    if episode is not None and episode.exchange != exchange.upper():
        raise ValueError(
            f"{contract} empirical episode belongs to {episode.exchange}, "
            f"not {exchange.upper()}"
        )
    target = (
        episode.last_trade
        if episode is not None
        else last_trade_date(contract, exchange, calendar)
    )
    return _trading_day_distance(asof, target, calendar)


def days_to_position_close(
    contract: str,
    exchange: str,
    asof: dt.date,
    calendar: TradingCalendar,
) -> int | None:
    """Return signed sessions to position close, or ``None`` when undefined."""
    close_date = position_close_date(contract, exchange, calendar)
    if close_date is None:
        return None
    return _trading_day_distance(asof, close_date, calendar)


def expiry_date(
    contract: str,
    exchange: str,
    calendar: TradingCalendar,
) -> dt.date:
    """Return the exchange-rule expiry date for ``contract``.

    SHFE delegates to its canonical in-repository contract-rule module and
    requires a loaded exchange calendar. Exchanges without a pinned rule fail
    with :class:`NotImplementedError`; this function never falls back to a
    weekday or calendar-day approximation.
    """
    exchange_id = exchange.upper()
    if exchange_id != "SHFE":
        raise NotImplementedError(
            f"{exchange_id} expiry rule is not authoritatively pinned"
        )
    _require_loaded_calendar(calendar)
    close_date = position_close_date(contract, exchange_id, calendar)
    assert close_date is not None
    return close_date


def days_to_expiry(
    contract: str,
    exchange: str,
    asof: dt.date,
    calendar: TradingCalendar,
) -> int:
    """Return trading sessions after ``asof`` through contract expiry.

    The result is zero on expiry. Dates after expiry return a negative count of
    trading sessions from expiry through ``asof``. Unsupported exchanges and
    unloaded calendars fail exactly as :func:`expiry_date` does.
    """
    expiry = expiry_date(contract, exchange, calendar)
    return _trading_day_distance(asof, expiry, calendar)


def _trading_day_distance(
    asof: dt.date,
    target: dt.date,
    calendar: TradingCalendar,
) -> int:
    if asof == target:
        return 0
    if asof < target:
        return sum(calendar.is_trading_day(day) for day in _dates_between(asof, target))
    return -sum(calendar.is_trading_day(day) for day in _dates_between(target, asof))


def _parse_four_digit_contract(contract: str) -> tuple[str, int, int]:
    match = re.fullmatch(r"([A-Za-z]+)(\d{2})(\d{2})", contract.strip())
    if match is None:
        raise ValueError(f"contract must use unambiguous YYMM digits: {contract}")
    month = int(match.group(3))
    if not 1 <= month <= 12:
        raise ValueError(f"invalid delivery month in contract: {contract}")
    year_digits = int(match.group(2))
    year = 2000 + year_digits if year_digits <= 50 else 1900 + year_digits
    return match.group(1).lower(), year, month


def _parse_three_digit_contract(contract: str) -> tuple[int, str, int]:
    match = re.fullmatch(r"([A-Za-z]+)(\d)(\d{2})", contract.strip())
    if match is None:
        raise ValueError(f"CZCE contract must use product plus YMM digits: {contract}")
    month = int(match.group(3))
    if not 1 <= month <= 12:
        raise ValueError(f"invalid delivery month in contract: {contract}")
    return int(match.group(2)), match.group(1).lower(), month


def _trading_days_in_month(
    calendar: TradingCalendar,
    year: int,
    month: int,
) -> list[dt.date]:
    return calendar.get_trading_days_between(
        dt.date(year, month, 1),
        dt.date(year, month, month_calendar.monthrange(year, month)[1]),
    )


def _dates_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Return calendar dates in ``(start, end]``."""
    return [
        start + dt.timedelta(days=offset) for offset in range(1, (end - start).days + 1)
    ]
