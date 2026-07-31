"""Synthetic pass-and-trip falsifiers for equity panel QC."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from echolon.panel.models import InstrumentMeta
from echolon.panel.qc import run_panel_qc


DATES = [dt.date(2020, 1, day) for day in range(2, 6)]


def _bars(*, trip_limit: bool = False) -> dict[str, pd.DataFrame]:
    close_raw = [10.0, 11.01 if trip_limit else 11.0, 10.5, 10.6]
    return {
        "000001.sz": pd.DataFrame(
            {
                "open": [10.0, 11.0, 10.5, 10.6],
                "high": [10.0, 11.0, 10.5, 10.6],
                "low": [10.0, 11.0, 10.5, 10.6],
                "close": [10.0, 11.0, 10.5, 10.6],
                "settle": [10.0, 11.0, 10.5, 10.6],
                "close_raw": close_raw,
                "volume": [100.0] * 4,
                "open_interest": [0.0] * 4,
                "contract": ["000001.sz"] * 4,
                "limit_up_price": [11.0] * 4,
                "limit_down_price": [9.0] * 4,
            },
            index=DATES,
        )
    }


def _meta() -> dict[str, InstrumentMeta]:
    return {
        "000001.sz": InstrumentMeta(
            instrument_id="000001.sz",
            sector="801780",
            multiplier=1.0,
            tick=0.01,
            margin_rate=1.0,
            commission=0.0,
            commission_type="notional",
            min_order_size=100.0,
            t_plus_one=True,
        )
    }


def _fundamentals(names: list[str]) -> dict[str, pd.DataFrame]:
    return {
        name: pd.DataFrame(
            {"net_profit_q": [1.0]}, index=[dt.date(2020, 1, 2)]
        )
        for name in names
    }


def _membership(counts: list[int]) -> pd.DataFrame:
    rows = []
    for date, count in zip(DATES, counts, strict=True):
        for number in range(count):
            rows.append(
                {"date": date, "instrument": f"{number + 1:06d}.sz"}
            )
    return pd.DataFrame(rows)


def _ids(report) -> set[str]:
    return {check.check_id for check in report.checks}


def test_equity_limit_band_trips_above_half_tick_tolerance() -> None:
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(trip_limit=True),
        curves={},
        instrument_meta=_meta(),
    )

    assert report.status == "FAIL"
    checks = [c for c in report.checks if c.check_id == "equity_limit_band"]
    assert len(checks) == 1
    assert checks[0].date == DATES[1]
    assert checks[0].severity == "ERROR"


def test_equity_limit_band_passes_at_exchange_bound() -> None:
    report = run_panel_qc(
        snapshot="equity", bars=_bars(), curves={}, instrument_meta=_meta()
    )

    assert "equity_limit_band" not in _ids(report)
    assert "daily_return_threshold" not in _ids(report)


def test_equity_limit_band_skips_suspended_carry_and_zero_volume() -> None:
    bars = _bars(trip_limit=True)
    bars["000001.sz"]["suspended"] = [0.0, 1.0, 0.0, 0.0]
    bars["000001.sz"].loc[DATES[1], "volume"] = 0.0

    report = run_panel_qc(
        snapshot="equity",
        bars=bars,
        curves={},
        instrument_meta=_meta(),
    )

    assert "equity_limit_band" not in _ids(report)
    assert "volume_nonzero" not in _ids(report)


def test_equity_limit_band_warns_on_first_row_after_eleven_day_gap() -> None:
    dates = [value.date() for value in pd.bdate_range("2020-01-02", periods=13)]
    frame = pd.DataFrame(
        {
            "open": [10.0, 7.3],
            "high": [10.0, 7.3],
            "low": [10.0, 7.3],
            "close": [10.0, 7.3],
            "settle": [10.0, 7.3],
            "close_raw": [10.0, 7.3],
            "volume": [100.0, 100.0],
            "suspended": [0.0, 0.0],
            "open_interest": [0.0, 0.0],
            "contract": ["000001.sz", "000001.sz"],
            "limit_up_price": [11.0, 11.0],
            "limit_down_price": [9.0, 9.0],
        },
        index=[dates[0], dates[-1]],
    )

    report = run_panel_qc(
        snapshot="equity",
        bars={"000001.sz": frame},
        curves={},
        instrument_meta=_meta(),
        trading_calendars={"000001.sz": dates},
    )

    skips = [
        check
        for check in report.checks
        if check.check_id == "limit_band_resumption_skip"
    ]
    assert report.status == "PASS_WITH_WARNINGS"
    assert len(skips) == 1
    assert skips[0].date == dates[-1]
    assert skips[0].severity == "WARN"
    assert "equity_limit_band" not in _ids(report)


def test_pit_consistency_trips_future_observation() -> None:
    future = pd.DataFrame(
        {"net_profit_q": [1.0]}, index=[dt.date(2020, 1, 6)]
    )
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        fundamentals={"000001.sz": future},
    )

    assert report.status == "FAIL"
    assert "pit_consistency" in _ids(report)


def test_pit_consistency_passes_observation_on_calendar_end() -> None:
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        fundamentals={
            "000001.sz": pd.DataFrame(
                {"net_profit_q": [1.0]}, index=[DATES[-1]]
            )
        },
    )

    assert "pit_consistency" not in _ids(report)


def test_survivorship_coverage_trips_missing_delisted_name() -> None:
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        universe=_membership([1, 1, 1, 1]),
        delisted_roster=pd.DataFrame(
            {"ts_code": ["000002.SZ"], "delist_date": ["20200105"]}
        ),
    )

    assert report.status == "FAIL"
    assert "survivorship_coverage" in _ids(report)


def test_survivorship_coverage_passes_historical_membership() -> None:
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        universe=_membership([2, 1, 1, 1]),
        delisted_roster=pd.DataFrame(
            {"ts_code": ["000002.SZ"], "delist_date": ["20200105"]}
        ),
    )

    assert "survivorship_coverage" not in _ids(report)


def test_universe_coverage_trips_one_day_drop_over_thirty_percent() -> None:
    names = [f"{number:06d}.sz" for number in range(1, 11)]
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        universe=_membership([10, 10, 10, 6]),
        fundamentals=_fundamentals(names),
    )

    assert report.status == "FAIL"
    assert "universe_coverage" in _ids(report)


def test_universe_coverage_passes_stable_counts() -> None:
    names = [f"{number:06d}.sz" for number in range(1, 11)]
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        universe=_membership([10, 10, 10, 10]),
        fundamentals=_fundamentals(names),
    )

    assert "universe_coverage" not in _ids(report)
    assert "fundamental_coverage" not in _ids(report)


def test_fundamental_coverage_error_below_fifty_percent() -> None:
    universe = _membership([4, 4, 4, 4])
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        universe=universe,
        fundamentals=_fundamentals(["000001.sz"]),
    )

    hard = [c for c in report.checks if c.check_id == "fundamental_coverage"]
    assert report.status == "FAIL"
    assert hard
    assert {check.severity for check in hard} == {"ERROR"}


def test_fundamental_coverage_warns_below_seventy_percent() -> None:
    universe = _membership([4, 4, 4, 4])
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        universe=universe,
        fundamentals=_fundamentals(["000001.sz", "000002.sz"]),
    )

    checks = [c for c in report.checks if c.check_id == "fundamental_coverage"]
    assert report.status == "PASS_WITH_WARNINGS"
    assert checks
    assert {check.severity for check in checks} == {"WARN"}


def test_pit_restatement_caveat_is_fixed_warning() -> None:
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        source_manifest={"pit_status": "ann_date_approx"},
    )

    caveat = [c for c in report.checks if c.check_id == "pit_restatement_caveat"]
    assert report.status == "PASS_WITH_WARNINGS"
    assert len(caveat) == 1
    assert caveat[0].severity == "WARN"
    assert caveat[0].message == (
        "Fundamental values may include later restatements; announcement "
        "dates are approximate first-observation dates "
        "(pit_status=ann_date_approx)."
    )


def test_pit_restatement_caveat_absent_for_first_print() -> None:
    report = run_panel_qc(
        snapshot="equity",
        bars=_bars(),
        curves={},
        source_manifest={"pit_status": "first_print"},
    )

    assert "pit_restatement_caveat" not in _ids(report)
