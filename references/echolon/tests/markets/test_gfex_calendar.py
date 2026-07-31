"""GFEX trading-calendar falsifiers (panel-v5, FV3 WP-X1b).

The bundled GFEX calendar is the union of every observed GFEX daily-bar date.
Its correctness bar is tri-source agreement: it must equal (1) an independent
re-derivation from the raw bars, (2) the DCE calendar over the GFEX-live window
(GFEX shares the national futures holiday schedule), and (3) a live Tushare
``trade_cal(exchange='GFEX')`` pull. Any disagreement is a STOP, not a
pick-a-winner. Legs (1)/(2) run offline when the datasets are present; leg (3)
is opt-in (network) and was verified live 2026-07-19 (see execution report).
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import os
from pathlib import Path

import pytest

from echolon.markets.gfex_calendar import gfex_trading_days

GFEX_PRODUCTS = ("si", "lc", "ps", "pt", "pd")
DCE_INSTRUMENTS = ("c", "eg", "i", "jd", "l", "m", "p", "pp", "v", "y")
WINDOW = (dt.date(2022, 12, 22), dt.date(2026, 7, 10))
EXPECTED_SESSIONS = 858


def test_bundled_gfex_calendar_is_well_formed() -> None:
    days = gfex_trading_days()
    assert len(days) == EXPECTED_SESSIONS
    assert days[0] == WINDOW[0]
    assert days[-1] == WINDOW[1]
    assert list(days) == sorted(days)
    assert len(set(days)) == len(days)
    assert all(day.weekday() < 5 for day in days)  # no weekend sessions


def test_bundled_calendar_matches_independent_raw_union(gfex_raw_bars: Path) -> None:
    assert _raw_gfex_union(gfex_raw_bars) == set(gfex_trading_days())


def test_gfex_calendar_equals_dce_over_live_window(p2_v4_panel: Path) -> None:
    lo, hi = WINDOW
    dce = {day for day in _dce_union(p2_v4_panel) if lo <= day <= hi}
    gfex = set(gfex_trading_days())
    only_gfex = sorted(gfex - dce)
    only_dce = sorted(dce - gfex)
    assert not only_gfex, f"GFEX sessions absent from DCE calendar: {only_gfex}"
    assert not only_dce, f"DCE sessions absent from GFEX calendar: {only_dce}"


@pytest.mark.skipif(
    not os.environ.get("DOLPHINQUANT_RUN_TUSHARE_GFEX"),
    reason="opt-in live Tushare check (set DOLPHINQUANT_RUN_TUSHARE_GFEX=1)",
)
def test_gfex_calendar_equals_live_tushare() -> None:  # pragma: no cover - network
    ts = pytest.importorskip("tushare")
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        pytest.skip("TUSHARE_TOKEN not set")
    pro = ts.pro_api(token)
    frame = pro.trade_cal(exchange="GFEX", start_date="20221222", end_date="20260710")
    open_days = {
        dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
        for s, is_open in zip(frame["cal_date"], frame["is_open"])
        if is_open == 1
    }
    assert open_days == set(gfex_trading_days())


# --------------------------------------------------------------------------- #
def _beijing_date(epoch_ms: int) -> dt.date:
    return (dt.datetime(1970, 1, 1)
            + dt.timedelta(milliseconds=epoch_ms, hours=8)).date()


def _raw_gfex_union(bars_root: Path) -> set[dt.date]:
    union: set[dt.date] = set()
    for product in GFEX_PRODUCTS:
        for path in sorted((bars_root / product).glob("*.csv.gz")):
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    union.add(_beijing_date(int(row["time"])))
    return union


def _dce_union(panel: Path) -> set[dt.date]:
    union: set[dt.date] = set()
    for instrument in DCE_INSTRUMENTS:
        with (panel / "contracts" / f"{instrument}.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            for row in csv.DictReader(handle):
                union.add(dt.date.fromisoformat(str(row["date"])[:10]))
    return union


