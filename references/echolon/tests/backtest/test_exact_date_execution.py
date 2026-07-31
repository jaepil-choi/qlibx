"""Falsifiers for exact-session target execution and contract rolls."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from echolon.backtest.book import BookBacktestConfig, DailyBookBacktester
from echolon.backtest.book.engine import _valuation_bar
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, RebalanceRecord, TargetBook


class _UnionPanel:
    snapshot_version = "union-calendar"

    def __init__(
        self,
        *,
        dates: list[dt.date],
        bars: dict[str, pd.DataFrame],
        contracts: dict[str, pd.DataFrame],
    ) -> None:
        self.instruments = list(bars)
        self.calendar = dates
        self._bars = bars
        self._contracts = contracts
        self.contract_bar_calls = 0
        self.contract_bar_asof_calls = 0
        self._meta = {
            instrument: InstrumentMeta(
                instrument_id=instrument,
                sector="generic",
                multiplier=1.0,
                tick=1.0,
                margin_rate=0.1,
                commission=1.0,
                commission_type="per_contract",
                close_today_commission=1.0,
                currency="RMB",
            )
            for instrument in bars
        }

    def view(self, date: dt.date) -> "_UnionView":
        return _UnionView(self, date)


class _UnionView:
    def __init__(self, panel: _UnionPanel, date: dt.date) -> None:
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
        self._panel.contract_bar_calls += 1
        frame = self._panel._contracts[instrument]
        rows = frame.loc[frame.index == self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        self._panel.contract_bar_asof_calls += 1
        frame = self._panel._contracts[instrument]
        rows = frame.loc[frame.index <= self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        if rows.empty:
            fallback = self._panel._bars[instrument]
            rows = fallback.loc[fallback.index <= self.date]
            rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._panel._meta[instrument]


class _DatedTargets:
    def __init__(self, targets: dict[dt.date, dict[str, float]]) -> None:
        self.targets = targets

    def rebalance(self, view, book: BookState):
        targets = self.targets.get(view.date, {})
        return (
            TargetBook(date=view.date, targets=targets),
            RebalanceRecord(date=view.date, instruments={}),
        )


class _ConstantTargets:
    def __init__(self, targets: dict[str, float]) -> None:
        self.targets = targets

    def rebalance(self, view, book: BookState):
        return (
            TargetBook(date=view.date, targets=self.targets),
            RebalanceRecord(date=view.date, instruments={}),
        )


def _main_bars(
    rows: list[tuple[dt.date, float, str]],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "settle": price,
                "volume": 1000,
                "open_interest": 5000,
                "contract": contract,
            }
            for _, price, contract in rows
        ],
        index=[date for date, _, _ in rows],
    )


def _contract_bars(
    rows: list[tuple[dt.date, float, str]],
) -> pd.DataFrame:
    frame = _main_bars(rows)
    return frame.assign(symbol=frame["contract"])


def _run(tmp_path: Path, panel: _UnionPanel, strategy) -> object:
    return DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=panel.calendar[0],
            end=panel.calendar[-1],
            initial_equity_rmb=1_000_000.0,
            panel_snapshot=panel.snapshot_version,
        ),
    )


def test_closed_instrument_target_defers_while_exact_peer_fills_and_newest_wins(
    tmp_path: Path,
):
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=index) for index in range(4)]
    first_rows = [(date, 10.0 + index, "F1") for index, date in enumerate(dates)]
    second_rows = [
        (dates[0], 20.0, "S1"),
        (dates[2], 30.0, "S1"),
        (dates[3], 31.0, "S1"),
    ]
    panel = _UnionPanel(
        dates=dates,
        bars={"first": _main_bars(first_rows), "second": _main_bars(second_rows)},
        contracts={
            "first": _contract_bars(first_rows),
            "second": _contract_bars(second_rows),
        },
    )
    strategy = _DatedTargets(
        {
            dates[0]: {"first": 1, "second": 1},
            dates[1]: {"first": 1, "second": 3},
            dates[2]: {"first": 1, "second": 3},
        }
    )

    result = _run(tmp_path, panel, strategy)

    assert [(trade.instrument, trade.date, trade.lots, trade.intended_price) for trade in result.trades] == [
        ("first", dates[1], 1.0, 11.0),
        ("second", dates[2], 3.0, 30.0),
    ]
    deferred = [event for event in result.events if event["type"] == "target_deferred"]
    assert deferred == [{
        "date": dates[1].isoformat(),
        "type": "target_deferred",
        "detail": {
            "instrument": "second",
            "target_lots": 1.0,
            "decision_date": dates[0].isoformat(),
            "reason": "missing_exact_main_bar",
        },
    }]
    replaced = [event for event in result.events if event["type"] == "target_replaced"]
    assert replaced[0]["detail"] == {
        "instrument": "second",
        "previous_target_lots": 1.0,
        "previous_decision_date": dates[0].isoformat(),
        "new_target_lots": 3.0,
        "new_decision_date": dates[1].isoformat(),
        "reason": "explicit_new_target",
    }


def test_closed_instrument_stale_main_cannot_materialize_roll(tmp_path: Path):
    dates = [dt.date(2024, 2, 1) + dt.timedelta(days=index) for index in range(5)]
    first_rows = [(date, 10.0, "F1") for date in dates]
    second_main = [
        (dates[0], 100.0, "S1"),
        (dates[1], 100.0, "S1"),
        (dates[3], 200.0, "S2"),
        (dates[4], 201.0, "S2"),
    ]
    second_contracts = [
        *second_main[:2],
        (dates[3], 110.0, "S1"),
        (dates[3], 200.0, "S2"),
        (dates[4], 201.0, "S2"),
    ]
    panel = _UnionPanel(
        dates=dates,
        bars={"first": _main_bars(first_rows), "second": _main_bars(second_main)},
        contracts={
            "first": _contract_bars(first_rows),
            "second": _contract_bars(second_contracts),
        },
    )

    result = _run(tmp_path, panel, _ConstantTargets({"second": 1}))

    assert [(trade.date, trade.contract, trade.intended_price) for trade in result.trades] == [
        (dates[1], "S1", 100.0),
        (dates[3], "S1", 110.0),
        (dates[3], "S2", 200.0),
    ]
    assert not any(trade.date == dates[2] for trade in result.trades)
    assert any(
        event["date"] == dates[2].isoformat()
        and event["type"] == "roll_deferred"
        and event["detail"]["reason"] == "missing_exact_main_bar"
        for event in result.events
    )


def test_exact_held_rows_never_invoke_asof_valuation_scan(tmp_path: Path):
    dates = [dt.date(2024, 2, 10) + dt.timedelta(days=index) for index in range(4)]
    first_rows = [(date, 10.0, "F1") for date in dates]
    second_rows = [(date, 100.0 + index, "S1") for index, date in enumerate(dates)]
    panel = _UnionPanel(
        dates=dates,
        bars={"first": _main_bars(first_rows), "second": _main_bars(second_rows)},
        contracts={
            "first": _contract_bars(first_rows),
            "second": _contract_bars(second_rows),
        },
    )

    _run(tmp_path, panel, _ConstantTargets({"second": 1}))

    assert panel.contract_bar_calls > 0
    assert panel.contract_bar_asof_calls == 0


def test_bars_only_valuation_uses_exact_matching_main_before_asof_scan():
    class BarsOnlyView:
        date = dt.date(2024, 2, 20)

        def __init__(self, current_contract: str | None) -> None:
            self.current_contract = current_contract
            self.asof_calls = 0

        def contract_bar(self, instrument: str, contract: str):
            return None

        def current_bar(self, instrument: str):
            if self.current_contract is None:
                return None
            return pd.Series({"contract": self.current_contract, "settle": 999.0})

        def contract_bar_asof(self, instrument: str, contract: str):
            self.asof_calls += 1
            return pd.Series({"contract": contract, "settle": 100.0})

    exact = BarsOnlyView("S1")
    assert _valuation_bar(exact, "second", "S1")["settle"] == 999.0
    assert exact.asof_calls == 0

    closed = BarsOnlyView(None)
    assert _valuation_bar(closed, "second", "S1")["settle"] == 100.0
    assert closed.asof_calls == 1

    different_main = BarsOnlyView("S2")
    assert _valuation_bar(different_main, "second", "S1")["settle"] == 100.0
    assert different_main.asof_calls == 1


def test_roll_requires_exact_held_contract_row_not_new_main_fallback(tmp_path: Path):
    dates = [dt.date(2024, 3, 1) + dt.timedelta(days=index) for index in range(5)]
    first_rows = [(date, 10.0, "F1") for date in dates]
    second_main = [
        (dates[0], 100.0, "S1"),
        (dates[1], 100.0, "S1"),
        (dates[2], 10_000.0, "S2"),
        (dates[3], 210.0, "S2"),
        (dates[4], 211.0, "S2"),
    ]
    second_contracts = [
        *second_main[:2],
        (dates[2], 200.0, "S2"),
        (dates[3], 115.0, "S1"),
        (dates[3], 210.0, "S2"),
        (dates[4], 211.0, "S2"),
    ]
    panel = _UnionPanel(
        dates=dates,
        bars={"first": _main_bars(first_rows), "second": _main_bars(second_main)},
        contracts={
            "first": _contract_bars(first_rows),
            "second": _contract_bars(second_contracts),
        },
    )

    result = _run(tmp_path, panel, _ConstantTargets({"second": 1}))

    assert [(trade.date, trade.contract, trade.intended_price) for trade in result.trades] == [
        (dates[1], "S1", 100.0),
        (dates[3], "S1", 115.0),
        (dates[3], "S2", 210.0),
    ]
    assert not any(trade.date == dates[2] for trade in result.trades)
    assert result.equity_curve[2].equity_rmb == result.equity_curve[1].equity_rmb
    assert panel.contract_bar_asof_calls == 2
    assert any(
        event["date"] == dates[2].isoformat()
        and event["type"] == "roll_deferred"
        and event["detail"]["reason"] == "missing_exact_held_contract_bar"
        for event in result.events
    )


def test_forced_liquidation_cancels_deferred_intent_instead_of_reopening(
    tmp_path: Path,
):
    dates = [dt.date(2024, 4, 1) + dt.timedelta(days=index) for index in range(4)]
    first_rows = [(date, 20_000_000.0, "F1") for date in dates]
    second_rows = [
        (dates[0], 20.0, "S1"),
        (dates[2], 30.0, "S1"),
        (dates[3], 31.0, "S1"),
    ]
    panel = _UnionPanel(
        dates=dates,
        bars={"first": _main_bars(first_rows), "second": _main_bars(second_rows)},
        contracts={
            "first": _contract_bars(first_rows),
            "second": _contract_bars(second_rows),
        },
    )
    strategy = _DatedTargets(
        {dates[0]: {"first": 1, "second": 1}}
    )

    result = _run(tmp_path, panel, strategy)

    assert [(trade.instrument, trade.date) for trade in result.trades] == [
        ("first", dates[1])
    ]
    assert not any(trade.instrument == "second" for trade in result.trades)
    assert [event["type"] for event in result.events] == [
        "target_deferred",
        "forced_liquidation",
        "target_cancelled",
    ]
    assert result.events[-1] == {
        "date": dates[1].isoformat(),
        "type": "target_cancelled",
        "detail": {
            "instrument": "second",
            "target_lots": 1.0,
            "decision_date": dates[0].isoformat(),
            "reason": "forced_liquidation",
        },
    }
