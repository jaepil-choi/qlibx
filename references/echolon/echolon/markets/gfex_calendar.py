"""Bundled GFEX trading calendar (empirically derived, tri-source validated).

The bundled ``data/gfex_trading_calendar.csv`` is the union of every observed
GFEX daily-bar date in the xtdata_expansion_20260711 dataset, built by
``scripts/build_gfex_expiry_data.py``. On 2026-07-19 this 858-session calendar
(2022-12-22..2026-07-10) was verified to agree EXACTLY with two independent
sources over the GFEX-live window: the DCE calendar from the p2_v4 panel and a
live Tushare ``trade_cal(exchange='GFEX')`` pull (see the WP-X1b execution
report). GFEX shares the national futures holiday schedule, so this equality is
the calendar's falsifier.
"""

from __future__ import annotations

import csv
import datetime as dt
from functools import lru_cache
from importlib.resources import files

from echolon.markets.shfe.trading_calendar import TradingCalendar


@lru_cache(maxsize=1)
def gfex_trading_days() -> tuple[dt.date, ...]:
    """Return the bundled GFEX session dates in ascending order."""
    resource = files("echolon.markets").joinpath("data/gfex_trading_calendar.csv")
    with resource.open("r", encoding="utf-8", newline="") as handle:
        days = [dt.date.fromisoformat(row["date"]) for row in csv.DictReader(handle)]
    return tuple(sorted(days))


def load_gfex_trading_calendar() -> TradingCalendar:
    """Return a loaded :class:`TradingCalendar` backed by the bundled GFEX days."""
    calendar = TradingCalendar()
    calendar._trading_days = set(gfex_trading_days())
    calendar._calendar_loaded = True
    return calendar
