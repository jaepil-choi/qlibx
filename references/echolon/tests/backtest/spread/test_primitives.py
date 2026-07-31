"""FV2-2b two-leg primitive falsifiers."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.backtest.spread import (
    SpreadPosition,
    SpreadSpec,
    legs_liquid,
    margin_required_rmb,
    round_trip_cost_rmb,
    tradable_window,
)
from echolon.markets.shfe.trading_calendar import TradingCalendar
from echolon.panel.models import InstrumentMeta


def _rb_meta() -> InstrumentMeta:
    return InstrumentMeta(
        instrument_id="rb",
        sector="ferrous",
        multiplier=10.0,
        tick=1.0,
        margin_rate=0.07,
        commission=1e-5,
        commission_type="percentage",
    )


def test_models_reject_invalid_or_degenerate_spreads() -> None:
    with pytest.raises(ValueError):
        SpreadSpec(instrument="rb", near_contract="RB2405", far_contract="RB2405")
    with pytest.raises(ValueError):
        SpreadSpec(
            instrument="rb", near_contract="RB2405", far_contract="RB2410", ratio=0
        )
    assert SpreadPosition(lots_near=1, lots_far=-1).lots_far == -1


def test_rb_round_trip_cost_anchor_is_exact_to_one_ten_thousandth_rmb() -> None:
    spread = SpreadSpec(instrument="rb", near_contract="RB2405", far_contract="RB2410")
    cost = round_trip_cost_rmb(spread, 3357.0, 3426.0, _rb_meta())
    assert cost.commission_rmb == pytest.approx(1.3566, abs=1e-4)
    assert cost.slippage_rmb == pytest.approx(40.0, abs=1e-4)
    assert cost.total_rmb == pytest.approx(41.3566, abs=1e-4)


def test_round_trip_cost_charges_ratio_on_far_leg() -> None:
    spread = SpreadSpec(
        instrument="rb", near_contract="RB2405", far_contract="RB2410", ratio=2
    )
    cost = round_trip_cost_rmb(spread, 100.0, 120.0, _rb_meta())
    assert cost.slippage_rmb == 60.0
    assert cost.commission_rmb == pytest.approx(0.068)


def test_margin_defaults_to_no_offset_and_never_invents_one() -> None:
    spread = SpreadSpec(instrument="rb", near_contract="RB2405", far_contract="RB2410")
    assert margin_required_rmb(spread, 3357.0, 3426.0, _rb_meta()) == pytest.approx(
        4748.1
    )
    assert (
        margin_required_rmb(spread, 3357.0, 3426.0, _rb_meta(), offset_margin=1200.0)
        == 1200.0
    )
    with pytest.raises(ValueError, match="offset_margin"):
        margin_required_rmb(spread, 3357.0, 3426.0, _rb_meta(), offset_margin=-1.0)


class _View:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def contracts_history(self, instrument: str, lookback: int) -> pd.DataFrame:
        assert instrument == "rb"
        assert lookback == 20
        return self.frame.copy()


def test_both_leg_liquidity_uses_each_contract_median() -> None:
    frame = pd.DataFrame(
        {
            "contract": ["RB2405"] * 3 + ["RB2410"] * 3,
            "volume": [100, 200, 300, 9, 11, 13],
        }
    )
    spread = SpreadSpec(instrument="rb", near_contract="RB2405", far_contract="RB2410")
    assert legs_liquid(spread, _View(frame), 10)
    assert not legs_liquid(spread, _View(frame), 12)


def test_both_leg_liquidity_fails_closed_for_missing_leg() -> None:
    frame = pd.DataFrame({"contract": ["RB2405"], "volume": [100]})
    spread = SpreadSpec(instrument="rb", near_contract="RB2405", far_contract="RB2410")
    assert not legs_liquid(spread, _View(frame), 1)


def test_delivery_window_excludes_five_trading_days_or_less() -> None:
    calendar = TradingCalendar()
    calendar._trading_days = {
        dt.date(2024, 3, day)
        for day in range(1, 30)
        if dt.date(2024, 3, day).weekday() < 5
    }
    calendar._calendar_loaded = True
    spread = SpreadSpec(instrument="m", near_contract="M2403", far_contract="M2405")
    assert tradable_window(
        spread, dt.date(2024, 3, 6), exchange="DCE", calendar=calendar
    )
    assert not tradable_window(
        spread, dt.date(2024, 3, 7), exchange="DCE", calendar=calendar
    )


def test_delivery_window_uses_shfe_position_close_not_last_trade() -> None:
    days = pd.bdate_range("2024-02-01", "2024-03-15")
    calendar = TradingCalendar()
    calendar._trading_days = {value.date() for value in days}
    calendar._calendar_loaded = True
    spread = SpreadSpec(instrument="rb", near_contract="RB2403", far_contract="RB2405")
    assert not tradable_window(
        spread, dt.date(2024, 2, 22), exchange="SHFE", calendar=calendar
    )


def test_delivery_window_consumes_czce_empirical_resolution() -> None:
    days = pd.bdate_range("2026-01-01", "2026-01-31")
    calendar = TradingCalendar()
    calendar._trading_days = {value.date() for value in days}
    calendar._calendar_loaded = True
    spread = SpreadSpec(instrument="rm", near_contract="RM601", far_contract="RM605")
    assert tradable_window(
        spread, dt.date(2026, 1, 5), exchange="CZCE", calendar=calendar
    )
    assert not tradable_window(
        spread, dt.date(2026, 1, 8), exchange="CZCE", calendar=calendar
    )
