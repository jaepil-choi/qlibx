from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from echolon.panel.models import InstrumentMeta
from spikes.p3_wp31_engine_spike import (
    SpikeConfig,
    run_backtrader_multidata_spike,
    run_purpose_built_spike,
)


@dataclass(frozen=True)
class _FakeView:
    date: dt.date
    bars_by_instrument: dict[str, pd.DataFrame]
    meta_by_instrument: dict[str, InstrumentMeta]

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self.bars_by_instrument[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self.meta_by_instrument[instrument]


class _FakePanel:
    def __init__(self, bars_by_instrument: dict[str, pd.DataFrame]) -> None:
        self.instruments = list(bars_by_instrument)
        self.calendar = list(next(iter(bars_by_instrument.values())).index)
        self._bars_by_instrument = bars_by_instrument
        self._meta_by_instrument = {
            instrument: InstrumentMeta(
                instrument_id=instrument,
                sector="test",
                multiplier=10.0,
                tick=0.01,
                margin_rate=0.10,
                commission=3.0,
                commission_type="per_contract",
                close_today_commission=None,
                currency="RMB",
            )
            for instrument in bars_by_instrument
        }

    def view(self, date: dt.date) -> _FakeView:
        return _FakeView(date, self._bars_by_instrument, self._meta_by_instrument)


def _bars(prices: list[float], contract: str) -> pd.DataFrame:
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=index) for index in range(len(prices))]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1 for price in prices],
            "low": [price - 1 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * len(prices),
            "open_interest": [5000] * len(prices),
            "contract": [contract] * len(prices),
        },
        index=dates,
    )


def test_purpose_built_spike_fills_next_day_open_and_tracks_margin() -> None:
    panel = _FakePanel({"al": _bars([100.0, 110.0, 120.0], "AL2401")})
    config = SpikeConfig(
        instruments=("al",),
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 1, 4),
        initial_cash_rmb=100_000.0,
        target_lots={"al": 2},
        slippage_bps=10.0,
    )

    result = run_purpose_built_spike(panel, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.date == dt.date(2024, 1, 3)
    assert trade.instrument == "al"
    assert trade.lots == 2
    assert trade.intended_price == 110.0
    assert trade.fill_price == 110.11
    assert trade.commission_rmb == 6.0
    latest = result.equity_curve[-1]
    assert latest.margin_used_rmb == 240.0
    assert latest.cash_rmb == 99_994.0
    assert latest.equity_rmb == 100_191.8
    assert result.events == []


def test_purpose_built_spike_forced_liquidates_when_margin_exceeds_equity() -> None:
    panel = _FakePanel({"cu": _bars([1000.0, 1000.0, 1000.0], "CU2401")})
    config = SpikeConfig(
        instruments=("cu",),
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 1, 4),
        initial_cash_rmb=1_000.0,
        target_lots={"cu": 20},
        slippage_bps=0.0,
    )

    result = run_purpose_built_spike(panel, config)

    assert result.events
    assert result.events[0].type == "forced_liquidation"
    assert result.equity_curve[-1].margin_used_rmb == 0.0


def test_backtrader_multidata_spike_routes_orders_per_feed_and_is_deterministic() -> None:
    panel = _FakePanel({
        "al": _bars([100.0, 101.0, 102.0], "AL2401"),
        "cu": _bars([200.0, 201.0, 202.0], "CU2401"),
    })
    config = SpikeConfig(
        instruments=("al", "cu"),
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 1, 4),
        initial_cash_rmb=100_000.0,
        target_lots={"al": 1, "cu": -1},
        slippage_bps=0.0,
    )

    first = run_backtrader_multidata_spike(panel, config)
    second = run_backtrader_multidata_spike(panel, config)

    assert {trade.instrument for trade in first.trades} == {"al", "cu"}
    assert first.determinism_hash == second.determinism_hash
    assert first.criteria["one_cash_account"] is True
    assert first.criteria["per_instrument_margin"] is False
    assert first.criteria["forced_liquidation"] is False
