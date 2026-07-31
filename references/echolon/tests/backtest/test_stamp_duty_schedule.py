"""Falsifier suite for the optional date-dependent sell-side stamp-duty schedule.

WP-R4 item 3. The engine must:
  * keep behaving byte-identically on BOTH the rebalance (execute) and the ROLL
    paths when no schedule is supplied (the FV2-safety property), and
  * switch the sell-side rate at an effective-date boundary, INCLUSIVE of the
    boundary date, when a schedule is supplied.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from echolon.backtest.book import BookBacktestConfig, DailyBookBacktester
from echolon.backtest.book.engine import (
    _Position,
    _normalize_stamp_duty_schedule,
    resolve_scheduled_stamp_duty_rate,
)
from echolon.panel.models import InstrumentMeta

# The rate schedule A-share round-2 configs will pin, sell-side only.
_ASHARE_SCHEDULE = [(dt.date(2016, 1, 1), 0.001), (dt.date(2023, 8, 28), 0.0005)]


# ---------------------------------------------------------------------------
# resolver + validation
# ---------------------------------------------------------------------------
def test_resolve_is_boundary_inclusive():
    frozen = _normalize_stamp_duty_schedule(_ASHARE_SCHEDULE)
    assert resolve_scheduled_stamp_duty_rate(frozen, dt.date(2016, 1, 1)) == 0.001
    assert resolve_scheduled_stamp_duty_rate(frozen, dt.date(2023, 8, 27)) == 0.001
    # The boundary date itself already pays the NEW (reduced) rate.
    assert resolve_scheduled_stamp_duty_rate(frozen, dt.date(2023, 8, 28)) == 0.0005
    assert resolve_scheduled_stamp_duty_rate(frozen, dt.date(2024, 1, 1)) == 0.0005


def test_resolve_before_first_effective_date_is_a_hard_failure():
    frozen = _normalize_stamp_duty_schedule(_ASHARE_SCHEDULE)
    with pytest.raises(ValueError, match="does not cover"):
        resolve_scheduled_stamp_duty_rate(frozen, dt.date(2015, 12, 31))


def test_normalize_rejects_malformed_and_passes_none_through():
    assert _normalize_stamp_duty_schedule(None) is None
    with pytest.raises(ValueError, match="non-empty"):
        _normalize_stamp_duty_schedule([])
    with pytest.raises(ValueError, match="strictly ascending"):
        _normalize_stamp_duty_schedule([(dt.date(2023, 8, 28), 0.0005), (dt.date(2016, 1, 1), 0.001)])
    with pytest.raises(ValueError, match="non-negative"):
        _normalize_stamp_duty_schedule([(dt.date(2016, 1, 1), -0.001)])


# ---------------------------------------------------------------------------
# execute (rebalance) path: boundary switch + absent-schedule byte-identity
# ---------------------------------------------------------------------------
class _EquityBar(pd.Series):
    pass


class _EquityView:
    def __init__(self, date: dt.date, price: float = 10.0) -> None:
        self.date = date
        self._price = price
        self._meta = InstrumentMeta(
            instrument_id="600000", sector="equity", multiplier=1.0, tick=0.01,
            margin_rate=1.0, commission=0.00025, commission_type="percentage",
            min_order_size=100.0, t_plus_one=True, stamp_duty_rate=0.0005,
            transfer_fee_rate=0.00001, min_commission=5.0,
        )

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [self._price], "high": [self._price], "low": [self._price],
                "close": [self._price], "settle": [self._price], "volume": [1000],
                "open_interest": [5000], "contract": ["600000"], "suspended": [0.0],
            },
            index=[self.date],
        )

    def current_bar(self, instrument: str):
        return self.bars(instrument, 1).iloc[0].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._meta


def _sell_commission(tmp_path: Path, on_date: dt.date, schedule) -> float:
    backtester = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, stamp_duty_schedule=schedule
    )
    backtester._last_buy_fill_dates = {}
    positions = {"600000": _Position(lots=100.0, avg_price=10.0, contract="600000",
                                     opened_date=dt.date(2023, 1, 1))}
    trades: list = []
    backtester._execute_targets(
        _EquityView(on_date), positions, {"600000": 0}, trades,
        BookBacktestConfig(start=on_date, end=on_date, initial_equity_rmb=1_000_000.0,
                           panel_snapshot="x"),
        [],
    )
    return trades[0].commission_rmb


def test_scheduled_sell_switches_rate_inclusive_of_the_boundary(tmp_path: Path):
    # notional = 10 * 1 * 100 = 1000; commission = max(0.25, 5.0) + 1000*rate + 0.01.
    before = _sell_commission(tmp_path / "a", dt.date(2023, 8, 27), _ASHARE_SCHEDULE)
    on_boundary = _sell_commission(tmp_path / "b", dt.date(2023, 8, 28), _ASHARE_SCHEDULE)
    assert before == pytest.approx(5.01 + 1000.0 * 0.001)     # 6.01, old 10bp
    assert on_boundary == pytest.approx(5.01 + 1000.0 * 0.0005)  # 5.51, new 5bp
    assert before - on_boundary == pytest.approx(0.5)


def test_absent_schedule_is_byte_identical_to_matching_flat_rate_on_execute(tmp_path: Path):
    # meta.stamp_duty_rate is 0.0005; a schedule that resolves to 0.0005 must
    # reproduce the flat-rate fee exactly, and both equal the hand value.
    flat = _sell_commission(tmp_path / "none", dt.date(2023, 8, 28), None)
    matched = _sell_commission(
        tmp_path / "match", dt.date(2023, 8, 28), [(dt.date(2016, 1, 1), 0.0005)]
    )
    assert flat == matched == pytest.approx(5.01 + 1000.0 * 0.0005)


# ---------------------------------------------------------------------------
# ROLL path: the schedule must not leak into contract-roll fees
# ---------------------------------------------------------------------------
class _RollPanel:
    snapshot_version = "roll"

    def __init__(self) -> None:
        self.instruments = ["al"]
        self.calendar = [dt.date(2024, 1, 2) + dt.timedelta(days=index) for index in range(5)]
        prices = [100.0, 100.0, 200.0, 200.0, 200.0]
        contracts = ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"]
        self._bars = {
            "al": pd.DataFrame(
                {
                    "open": prices, "high": prices, "low": prices, "close": prices,
                    "settle": prices, "volume": [1000] * 5, "open_interest": [5000] * 5,
                    "contract": contracts,
                },
                index=self.calendar,
            )
        }
        self._contracts = {
            "al": pd.DataFrame(
                [
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "settle": 110.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                ],
                index=[self.calendar[0], self.calendar[1], self.calendar[2], self.calendar[2], self.calendar[3]],
            )
        }
        self._meta = {
            "al": InstrumentMeta(
                instrument_id="al", sector="base", multiplier=5.0, tick=1.0,
                margin_rate=0.09, commission=0.0, commission_type="per_contract",
                close_today_commission=0.0, currency="RMB",
            )
        }

    def view(self, date: dt.date) -> "_RollView":
        return _RollView(self, date)


class _RollView:
    def __init__(self, panel: _RollPanel, date: dt.date) -> None:
        self._panel = panel
        self.date = date

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self._panel._bars[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def current_bar(self, instrument: str):
        frame = self._panel._bars[instrument]
        rows = frame.loc[frame.index == self.date]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        frame = self._panel._contracts[instrument]
        rows = frame.loc[frame.index == self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        frame = self._panel._contracts[instrument]
        rows = frame.loc[frame.index <= self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._panel._meta[instrument]


class _ConstantLong:
    def rebalance(self, view, book):
        from echolon.portfolio import RebalanceRecord, TargetBook
        return (TargetBook(date=view.date, targets={"al": 1}),
                RebalanceRecord(date=view.date, instruments={}))


def _run_roll(tmp_path: Path, schedule) -> str:
    return DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None,
        stamp_duty_schedule=schedule,
    ).run(
        _ConstantLong(),
        _RollPanel(),
        BookBacktestConfig(start=dt.date(2024, 1, 2), end=dt.date(2024, 1, 6),
                           initial_equity_rmb=100_000.0, panel_snapshot="roll"),
    ).summary.determinism_hash


def test_schedule_does_not_leak_into_roll_path(tmp_path: Path):
    # Contract rolls (and buy legs) never pay stamp duty; even an absurd scheduled
    # rate must leave the roll-exercising book byte-identical to the no-schedule run.
    no_schedule = _run_roll(tmp_path / "none", None)
    big_rate = _run_roll(tmp_path / "big", [(dt.date(2016, 1, 1), 0.5)])
    assert no_schedule == big_rate


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
