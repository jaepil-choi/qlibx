from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from echolon.backtest.book import (
    BookBacktestConfig,
    DailyBookBacktester,
    verify_full_result_manifest_sha256,
)
from echolon.live.book import DiffOrder, TargetExecutor
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, RebalanceRecord, TargetBook


class _Panel:
    snapshot_version = "synthetic_book"

    def __init__(self) -> None:
        self.instruments = ["al", "cu"]
        self.calendar = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(5)]
        self._bars = {
            "al": _bars([19000.0, 19010.0, 19020.0, 19030.0, 19040.0], "al2402"),
            "cu": _bars([70000.0] * 5, "cu2402"),
        }
        self._contracts = {
            instrument: frame.assign(symbol=frame["contract"])
            for instrument, frame in self._bars.items()
        }
        self._meta = {
            "al": InstrumentMeta(
                instrument_id="al",
                sector="base",
                multiplier=5.0,
                tick=0.01,
                margin_rate=0.09,
                commission=3.01,
                commission_type="per_contract",
                close_today_commission=3.01,
                currency="RMB",
            ),
            "cu": InstrumentMeta(
                instrument_id="cu",
                sector="base",
                multiplier=5.0,
                tick=10.0,
                margin_rate=0.09,
                commission=0.00005,
                commission_type="percentage",
                close_today_commission=None,
                currency="RMB",
            ),
        }

    def view(self, date: dt.date):
        return _View(date, self._bars, self._meta, self._contracts)


class _View:
    def __init__(self, date, bars, meta, contracts) -> None:
        self.date = date
        self._bars = bars
        self._meta = meta
        self._contracts = contracts

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self._bars[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def current_bar(self, instrument: str):
        frame = self._bars[instrument]
        rows = frame.loc[frame.index == self.date]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        frame = self._contracts[instrument]
        rows = frame.loc[frame.index == self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        if rows.empty:
            return None
        return rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        frame = self._contracts[instrument]
        rows = frame.loc[frame.index <= self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        if rows.empty:
            fallback = self._bars[instrument]
            rows = fallback.loc[fallback.index <= self.date]
            rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._meta[instrument]


class _StaticStrategy:
    def __init__(self, targets: dict[str, int]) -> None:
        self.targets = targets

    def rebalance(self, view, book: BookState):
        return TargetBook(date=view.date, targets=dict(self.targets)), RebalanceRecord(date=view.date, instruments={})


class _DatedStrategy:
    def __init__(self, targets_by_date: dict[dt.date, dict[str, int]]) -> None:
        self.targets_by_date = targets_by_date

    def rebalance(self, view, book: BookState):
        targets = self.targets_by_date.get(view.date, {})
        return TargetBook(date=view.date, targets=dict(targets)), RebalanceRecord(date=view.date, instruments={})


def _bars(prices: list[float], contract: str) -> pd.DataFrame:
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(len(prices))]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * len(prices),
            "open_interest": [5000] * len(prices),
            "contract": [contract] * len(prices),
        },
        index=dates,
    )


def test_book_backtester_rebalance_interval_skips_alternate_weeks(tmp_path: Path):
    backtester = DailyBookBacktester(
        output_dir=tmp_path,
        rebalance_weekday=4,
        rebalance_interval_weeks=2,
    )
    start = dt.date(2024, 1, 1)

    assert backtester._is_rebalance_date(dt.date(2024, 1, 5), start)
    assert not backtester._is_rebalance_date(dt.date(2024, 1, 12), start)
    assert backtester._is_rebalance_date(dt.date(2024, 1, 19), start)


def test_book_backtester_rejects_invalid_rebalance_interval(tmp_path: Path):
    with pytest.raises(ValueError, match="rebalance_interval_weeks"):
        DailyBookBacktester(output_dir=tmp_path, rebalance_interval_weeks=0)


def test_book_backtester_applies_s11_slippage_and_commission(tmp_path: Path):
    panel = _Panel()
    backtester = DailyBookBacktester(output_dir=tmp_path, slippage_bps=3.0, rebalance_weekday=None)

    result = backtester.run(
        _StaticStrategy({"al": 1, "cu": 1}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
        ),
    )

    al_trade = next(trade for trade in result.trades if trade.instrument == "al")
    cu_trade = next(trade for trade in result.trades if trade.instrument == "cu")
    assert al_trade.date == dt.date(2024, 1, 3)
    assert al_trade.intended_price == 19010.0
    assert al_trade.fill_price == 19015.71
    assert al_trade.commission_rmb == pytest.approx(3.01, abs=0.01)
    assert cu_trade.commission_rmb == pytest.approx(17.50, abs=0.01)
    assert (tmp_path / "equity_curve.csv").is_file()
    assert (tmp_path / "trades.csv").is_file()
    assert json.loads((tmp_path / "summary.json").read_text())["determinism_hash"] == result.summary.determinism_hash


def test_book_backtester_applies_explicit_commission_stress_multiplier(
    tmp_path: Path,
) -> None:
    panel = _Panel()
    result = DailyBookBacktester(
        output_dir=tmp_path / "stress", slippage_bps=0.0, rebalance_weekday=None
    ).run(
        _StaticStrategy({"al": 1, "cu": 1}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
            commission_multiplier=2.0,
        ),
    )

    al_trade = next(trade for trade in result.trades if trade.instrument == "al")
    cu_trade = next(trade for trade in result.trades if trade.instrument == "cu")
    assert al_trade.commission_rmb == pytest.approx(6.02, abs=0.01)
    assert cu_trade.commission_rmb == pytest.approx(35.0, abs=0.01)
    assert result.summary.fees_total_rmb == pytest.approx(
        sum(trade.commission_rmb for trade in result.trades)
    )
    baseline = DailyBookBacktester(
        output_dir=tmp_path / "baseline", slippage_bps=0.0, rebalance_weekday=None
    ).run(
        _StaticStrategy({"al": 1, "cu": 1}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
        ),
    )
    assert result.runtime_manifest.config["commission_multiplier"] == 2.0
    assert "commission_multiplier" not in baseline.runtime_manifest.config
    assert (
        result.summary.full_result_manifest_sha256
        != baseline.summary.full_result_manifest_sha256
    )
    assert verify_full_result_manifest_sha256(result)


def test_default_commission_multiplier_preserves_legacy_serialization() -> None:
    payload = {
        "start": dt.date(2024, 1, 2),
        "end": dt.date(2024, 1, 6),
        "initial_equity_rmb": 700_000.0,
        "panel_snapshot": "synthetic_book",
    }
    implicit = BookBacktestConfig(**payload)
    explicit = BookBacktestConfig(**payload, commission_multiplier=1.0)
    assert implicit.model_dump(mode="json") == explicit.model_dump(mode="json")
    assert "commission_multiplier" not in implicit.model_dump(mode="json")
    assert (
        BookBacktestConfig.model_validate(explicit.model_dump(mode="json"))
        .commission_multiplier
        == 1.0
    )


def test_target_close_today_uses_stressed_close_today_commission(tmp_path: Path):
    from echolon.backtest.book.engine import _Position

    panel = _Panel()
    date = panel.calendar[1]
    panel._meta["al"] = panel._meta["al"].model_copy(
        update={"commission": 3.0, "close_today_commission": 11.0}
    )
    positions = {
        "al": _Position(
            lots=1.0,
            avg_price=19_010.0,
            contract="al2402",
            opened_date=date,
        )
    }
    trades = []
    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    )._execute_targets(
        panel.view(date),
        positions,
        {"al": 0.0},
        trades,
        BookBacktestConfig(
            start=panel.calendar[0],
            end=panel.calendar[-1],
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
            commission_multiplier=2.0,
        ),
        [],
    )

    assert result.cash_delta == -22.0
    assert len(trades) == 1
    assert trades[0].side == "SELL"
    assert trades[0].close_today is True
    assert trades[0].commission_rmb == 22.0
    assert trades[0].position_after == 0.0


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_book_config_rejects_invalid_commission_multiplier(value: float) -> None:
    with pytest.raises(ValueError):
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
            commission_multiplier=value,
        )


def test_book_backtester_uses_per_instrument_slippage_tiers(tmp_path: Path):
    panel = _Panel()
    backtester = DailyBookBacktester(output_dir=tmp_path, slippage_bps=3.0, rebalance_weekday=None)

    result = backtester.run(
        _StaticStrategy({"al": 1, "cu": 1}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
            slippage_bps_by_instrument={"al": 10.0, "cu": 1.0},
        ),
    )

    al_trade = next(trade for trade in result.trades if trade.instrument == "al")
    cu_trade = next(trade for trade in result.trades if trade.instrument == "cu")
    assert al_trade.fill_price == 19029.01
    assert cu_trade.fill_price == 70010.0
    assert al_trade.slippage_rmb == pytest.approx((19029.01 - 19010.0) * 5.0)
    assert cu_trade.slippage_rmb == pytest.approx((70010.0 - 70000.0) * 5.0)


def test_book_backtester_forced_liquidation_event(tmp_path: Path):
    # This is the explicitly uncertified legacy branch, which still synthetic-clears
    # positions. Costed liquidation for the next trial uses strict lifecycle and the
    # exact-close helper covered in test_terminal_lifecycle.py.
    panel = _Panel()
    backtester = DailyBookBacktester(output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None)

    result = backtester.run(
        _StaticStrategy({"cu": 100}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=10_000.0,
            panel_snapshot="synthetic_book",
        ),
    )

    assert result.events
    assert result.events[0]["type"] == "forced_liquidation"
    assert result.equity_curve[-1].margin_used_rmb == 0.0


def test_book_backtester_artifacts_are_deterministic(tmp_path: Path):
    panel = _Panel()
    config = BookBacktestConfig(
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 1, 6),
        initial_equity_rmb=700_000.0,
        panel_snapshot="synthetic_book",
    )
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = DailyBookBacktester(output_dir=first_dir, slippage_bps=3.0, rebalance_weekday=None).run(
        _StaticStrategy({"al": 1, "cu": -1}),
        panel,
        config,
    )
    second = DailyBookBacktester(output_dir=second_dir, slippage_bps=3.0, rebalance_weekday=None).run(
        _StaticStrategy({"al": 1, "cu": -1}),
        panel,
        config,
    )

    assert first.summary.determinism_hash == second.summary.determinism_hash
    for name in ("equity_curve.csv", "trades.csv", "daily_returns.csv", "events.jsonl", "summary.json"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()


def test_fill_refusal_is_auditable_and_does_not_block_other_names(tmp_path: Path):
    panel = _Panel()
    new_dates = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(5)]
    panel.calendar = new_dates
    for instrument, frame in panel._bars.items():
        frame.index = new_dates
        frame["suspended"] = 0.0
        frame["limit_up_price"] = float("nan")
        frame["limit_down_price"] = float("nan")
        panel._contracts[instrument] = frame.assign(symbol=frame["contract"])
    panel._bars["al"].loc[new_dates[1], "suspended"] = 1.0

    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=0
    ).run(
        _StaticStrategy({"al": 1, "cu": 1}),
        panel,
        BookBacktestConfig(
            start=new_dates[0], end=new_dates[-1], initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
        ),
    )

    al_trades = [trade for trade in result.trades if trade.instrument == "al"]
    assert [(trade.date, trade.lots) for trade in al_trades] == [(new_dates[2], 1.0)]
    assert any(trade.instrument == "cu" for trade in result.trades)
    assert result.events == [{
        "date": new_dates[1].isoformat(),
        "type": "fill_refused",
        "detail": {
            "instrument": "al",
            "side": "BUY",
            "lots": 1.0,
            "target_lots": 1.0,
            "decision_date": new_dates[0].isoformat(),
            "reason": "suspended",
            "pending_action": "retained",
        },
    }]


@pytest.mark.parametrize(
    ("target", "limit_column", "limit_price", "expected_reason"),
    [(1, "limit_up_price", 19010.0, "limit_up"), (-1, "limit_down_price", 19010.0, "limit_down")],
)
def test_locked_limit_open_refuses_fill(
    tmp_path: Path, target: int, limit_column: str, limit_price: float, expected_reason: str
):
    panel = _Panel()
    new_dates = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(5)]
    panel.calendar = new_dates
    for instrument, frame in panel._bars.items():
        frame.index = new_dates
        frame["suspended"] = 0.0
        frame["limit_up_price"] = float("nan")
        frame["limit_down_price"] = float("nan")
        panel._contracts[instrument] = frame.assign(symbol=frame["contract"])
    panel._bars["al"].loc[new_dates[1], limit_column] = limit_price

    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=0
    ).run(
        _StaticStrategy({"al": target}), panel,
        BookBacktestConfig(start=new_dates[0], end=new_dates[-1], initial_equity_rmb=700_000.0,
                           panel_snapshot="synthetic_book"),
    )

    assert [(trade.date, trade.lots) for trade in result.trades] == [
        (new_dates[2], 1.0)
    ]
    assert result.events == [{
        "date": new_dates[1].isoformat(),
        "type": "fill_refused",
        "detail": {
            "instrument": "al",
            "side": "BUY" if target > 0 else "SELL",
            "lots": 1.0,
            "target_lots": float(target),
            "decision_date": new_dates[0].isoformat(),
            "reason": expected_reason,
            "pending_action": "retained",
        },
    }]


def test_buy_one_tick_below_limit_up_fills(tmp_path: Path):
    panel = _Panel()
    dates = [dt.date(2023, 2, 6) + dt.timedelta(days=i) for i in range(5)]
    panel.calendar = dates
    for instrument, frame in panel._bars.items():
        frame.index = dates
        frame["suspended"] = 0.0
        frame["limit_up_price"] = float("nan")
        frame["limit_down_price"] = float("nan")
        panel._contracts[instrument] = frame.assign(symbol=frame["contract"])
    panel._bars["al"].loc[dates[1], "limit_up_price"] = 19010.01

    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=0
    ).run(
        _StaticStrategy({"al": 1}), panel,
        BookBacktestConfig(start=dates[0], end=dates[-1], initial_equity_rmb=700_000.0,
                           panel_snapshot="synthetic_book"),
    )
    assert len(result.trades) == 1
    assert result.trades[0].intended_price == 19010.0


@pytest.mark.parametrize(
    ("price", "target", "expected"),
    [(10.0, 200, 5.02), (10.0, -200, 6.02), (50.0, 10_000, 130.0)],
)
def test_engine_equity_cost_anchors_end_to_end(
    tmp_path: Path, price: float, target: int, expected: float
):
    panel = _Panel()
    dates = [dt.date(2023, 3, 6) + dt.timedelta(days=i) for i in range(5)]
    panel.calendar = dates
    panel.instruments = ["al"]
    panel._bars = {"al": _bars([price] * 5, "600000")}
    panel._bars["al"].index = dates
    panel._contracts = {"al": panel._bars["al"].assign(symbol="600000")}
    panel._meta["al"] = InstrumentMeta(
        instrument_id="al", sector="equity", multiplier=1.0, tick=0.01,
        margin_rate=1.0, commission=0.00025, commission_type="percentage",
        min_order_size=100.0, t_plus_one=True, stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00001, min_commission=5.0,
    )
    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=0
    ).run(
        _StaticStrategy({"al": target}), panel,
        BookBacktestConfig(start=dates[0], end=dates[-1], initial_equity_rmb=1_000_000.0,
                           panel_snapshot="synthetic_equity"),
    )
    assert result.trades[0].commission_rmb == pytest.approx(expected, abs=0.01)


def test_t_plus_one_rejects_same_day_sell_and_allows_next_day(tmp_path: Path):
    from echolon.backtest.book.engine import _Position

    panel = _Panel()
    dates = [dt.date(2023, 4, 3), dt.date(2023, 4, 4)]
    for instrument, frame in panel._bars.items():
        frame.index = [dates[0], dates[1], *[dates[1] + dt.timedelta(days=i) for i in range(1, 4)]]
    panel._meta["al"] = panel._meta["al"].model_copy(update={"t_plus_one": True})
    backtester = DailyBookBacktester(output_dir=tmp_path, slippage_bps=0.0)
    positions = {"al": _Position()}
    trades = []
    config = BookBacktestConfig(start=dates[0], end=dates[1], initial_equity_rmb=1.0,
                                panel_snapshot="synthetic")
    backtester._execute_targets(_View(dates[0], panel._bars, panel._meta, panel._contracts),
                                positions, {"al": 100}, trades, config, [])
    with pytest.raises(RuntimeError, match=r"T\+1"):
        backtester._execute_targets(_View(dates[0], panel._bars, panel._meta, panel._contracts),
                                    positions, {"al": 0}, trades, config, [])
    backtester._execute_targets(_View(dates[1], panel._bars, panel._meta, panel._contracts),
                                positions, {"al": 0}, trades, config, [])
    assert positions["al"].lots == 0


def test_book_backtester_roll_preserves_accrued_contract_pnl(tmp_path: Path):
    class RollingPanel(_Panel):
        def __init__(self) -> None:
            super().__init__()
            dates = self.calendar
            self._bars["al"] = pd.DataFrame(
                {
                    "open": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "high": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "low": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "close": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "settle": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "volume": [1000] * 5,
                    "open_interest": [5000] * 5,
                    "contract": ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"],
                },
                index=dates,
            )
            self._contracts["al"] = pd.DataFrame(
                [
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "settle": 110.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                ],
                index=[dates[0], dates[1], dates[2], dates[2], dates[3]],
            )
            self._meta["al"] = self._meta["al"].model_copy(update={"commission": 0.0, "close_today_commission": 0.0})

    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        _StaticStrategy({"al": 1}),
        RollingPanel(),
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=100_000.0,
            panel_snapshot="rolling_synthetic",
        ),
    )

    assert [trade.contract for trade in result.trades] == ["AL2401", "AL2401", "AL2402"]
    assert result.trades[1].realized_pnl_rmb == pytest.approx(50.0)
    assert result.equity_curve[-1].equity_rmb == pytest.approx(100_050.0)


def test_roll_close_and_open_both_use_stressed_commission(tmp_path: Path):
    panel = _Panel()
    dates = panel.calendar
    panel._bars["al"] = pd.DataFrame(
        {
            "open": [100.0, 100.0, 200.0, 200.0, 200.0],
            "high": [100.0, 100.0, 200.0, 200.0, 200.0],
            "low": [100.0, 100.0, 200.0, 200.0, 200.0],
            "close": [100.0, 100.0, 200.0, 200.0, 200.0],
            "settle": [100.0, 100.0, 200.0, 200.0, 200.0],
            "volume": [1000] * 5,
            "open_interest": [5000] * 5,
            "contract": ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"],
        },
        index=dates,
    )
    panel._contracts["al"] = pd.DataFrame(
        [
            {"contract": "AL2401", "open": 100.0},
            {"contract": "AL2401", "open": 100.0},
            {"contract": "AL2401", "open": 110.0},
            {"contract": "AL2402", "open": 200.0},
            {"contract": "AL2402", "open": 200.0},
        ],
        index=[dates[0], dates[1], dates[2], dates[2], dates[3]],
    ).assign(
        symbol=lambda frame: frame["contract"],
        high=lambda frame: frame["open"],
        low=lambda frame: frame["open"],
        close=lambda frame: frame["open"],
        settle=lambda frame: frame["open"],
        volume=1000,
        open_interest=5000,
    )
    panel._meta["al"] = panel._meta["al"].model_copy(
        update={"commission": 3.01, "close_today_commission": 9.0}
    )

    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        _StaticStrategy({"al": 1}),
        panel,
        BookBacktestConfig(
            start=dates[0],
            end=dates[-1],
            initial_equity_rmb=100_000.0,
            panel_snapshot="rolling_stress_synthetic",
            commission_multiplier=2.0,
        ),
    )

    al_trades = [trade for trade in result.trades if trade.instrument == "al"]
    assert [(trade.contract, trade.side) for trade in al_trades] == [
        ("AL2401", "BUY"),
        ("AL2401", "SELL"),
        ("AL2402", "BUY"),
    ]
    assert [trade.commission_rmb for trade in al_trades] == pytest.approx(
        [6.02, 6.02, 6.02]
    )
    assert al_trades[1].close_today is False


def test_book_backtester_closes_held_contract_when_flattening_on_roll_date(tmp_path: Path):
    class RollingPanel(_Panel):
        def __init__(self) -> None:
            super().__init__()
            dates = self.calendar
            self._bars["al"] = pd.DataFrame(
                {
                    "open": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "high": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "low": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "close": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "settle": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "volume": [1000] * 5,
                    "open_interest": [5000] * 5,
                    "contract": ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"],
                },
                index=dates,
            )
            self._contracts["al"] = pd.DataFrame(
                [
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "settle": 110.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                ],
                index=[dates[0], dates[1], dates[2], dates[2]],
            )
            self._meta["al"] = self._meta["al"].model_copy(update={"commission": 0.0, "close_today_commission": 0.0})

    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        _DatedStrategy(
            {
                dt.date(2024, 1, 2): {"al": 1},
                dt.date(2024, 1, 3): {"al": 0},
            }
        ),
        RollingPanel(),
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=100_000.0,
            panel_snapshot="rolling_synthetic",
        ),
    )

    assert [trade.contract for trade in result.trades] == ["AL2401", "AL2401"]
    assert [trade.position_after for trade in result.trades] == [1, 0]
    assert result.trades[1].realized_pnl_rmb == pytest.approx(50.0)
    assert result.equity_curve[-1].equity_rmb == pytest.approx(100_050.0)


@pytest.mark.parametrize(
    ("pending_target", "expected_contracts", "expected_sides", "expected_after"),
    [
        (0, ["AL2401", "AL2401"], ["BUY", "SELL"], [1.0, 0.0]),
        (
            -1,
            ["AL2401", "AL2401", "AL2402"],
            ["BUY", "SELL", "SELL"],
            [1.0, 0.0, -1.0],
        ),
    ],
)
def test_roll_with_pending_absolute_target_executes_once(
    tmp_path: Path,
    pending_target: int,
    expected_contracts: list[str],
    expected_sides: list[str],
    expected_after: list[float],
):
    panel = _Panel()
    dates = panel.calendar
    main = _bars([100.0, 100.0, 200.0, 200.0, 200.0], "AL2401")
    main["contract"] = ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"]
    held = _bars([100.0, 100.0, 110.0], "AL2401")
    new = _bars([200.0, 200.0, 200.0], "AL2402")
    new.index = dates[2:]
    panel._bars["al"] = main
    panel._contracts["al"] = pd.concat([held, new]).assign(
        symbol=lambda frame: frame["contract"]
    ).sort_index()

    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        _DatedStrategy(
            {dates[0]: {"al": 1}, dates[1]: {"al": pending_target}}
        ),
        panel,
        BookBacktestConfig(
            start=dates[0], end=dates[2], initial_equity_rmb=100_000.0,
            panel_snapshot="pending_roll_target",
        ),
    )
    al_trades = [trade for trade in result.trades if trade.instrument == "al"]

    assert [trade.contract for trade in al_trades] == expected_contracts
    assert [trade.side for trade in al_trades] == expected_sides
    assert [trade.position_after for trade in al_trades] == expected_after


def test_target_book_public_contract_defines_omission_as_absolute_zero():
    description = TargetBook.model_fields["targets"].description
    assert description is not None
    assert "Absolute target lots" in description
    assert "omitted" in description and "zero" in description


def test_new_absolute_book_omission_cancels_flat_deferred_open_with_live_parity(
    tmp_path: Path,
):
    panel = _Panel()
    dates = panel.calendar
    panel._bars["al"] = panel._bars["al"].drop(index=dates[1])
    panel._contracts["al"] = panel._contracts["al"].drop(index=dates[1])
    strategy = _DatedStrategy(
        {dates[0]: {"al": 1}, dates[1]: {}}
    )

    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=dates[0], end=dates[-1], initial_equity_rmb=700_000.0,
            panel_snapshot="absolute_target_flat",
        ),
    )
    live_plan = TargetExecutor(
        router=None, book_id="generic", symbol_map={"al": "AL"}
    ).plan(TargetBook(date=dates[1], targets={}), current_lots={})

    assert live_plan == []
    assert not any(trade.instrument == "al" for trade in result.trades)
    assert result.events == [
        {
            "date": dates[1].isoformat(),
            "type": "target_deferred",
            "detail": {
                "instrument": "al",
                "target_lots": 1.0,
                "decision_date": dates[0].isoformat(),
                "reason": "missing_exact_main_bar",
            },
        },
        {
            "date": dates[1].isoformat(),
            "type": "target_cancelled",
            "detail": {
                "instrument": "al",
                "target_lots": 1.0,
                "decision_date": dates[0].isoformat(),
                "superseding_decision_date": dates[1].isoformat(),
                "reason": "omitted_by_new_target_book",
            },
        },
    ]


def test_new_absolute_book_omission_flattens_held_name_with_live_parity(
    tmp_path: Path,
):
    panel = _Panel()
    dates = panel.calendar
    strategy = _DatedStrategy(
        {dates[0]: {"al": 1}, dates[1]: {}}
    )

    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=dates[0], end=dates[-1], initial_equity_rmb=700_000.0,
            panel_snapshot="absolute_target_held",
        ),
    )
    live_plan = TargetExecutor(
        router=None, book_id="generic", symbol_map={"al": "AL"}
    ).plan(TargetBook(date=dates[1], targets={}), current_lots={"al": 1})

    assert live_plan == [
        DiffOrder(instrument="al", symbol="AL", intent="EXIT_LONG", volume=1)
    ]
    assert [
        (trade.date, trade.side, trade.lots)
        for trade in result.trades
        if trade.instrument == "al"
    ] == [
        (dates[1], "BUY", 1.0),
        (dates[2], "SELL", 1.0),
    ]
