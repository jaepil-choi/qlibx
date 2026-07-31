"""P3 WP3.1 portfolio-engine spike prototypes.

This module is deliberately outside the public ``echolon`` package. It keeps
the competing spike code available for review without making either prototype a
supported API.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

import backtrader as bt
import pandas as pd


@dataclass(frozen=True)
class SpikeConfig:
    instruments: tuple[str, ...]
    start: dt.date
    end: dt.date
    initial_cash_rmb: float
    target_lots: Mapping[str, int]
    slippage_bps: float = 3.0


@dataclass(frozen=True)
class SpikeTrade:
    date: dt.date
    instrument: str
    contract: str
    lots: int
    intended_price: float
    fill_price: float
    slippage_rmb: float
    commission_rmb: float


@dataclass(frozen=True)
class SpikeEquityPoint:
    date: dt.date
    equity_rmb: float
    cash_rmb: float
    margin_used_rmb: float


@dataclass(frozen=True)
class SpikeEvent:
    date: dt.date
    type: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class SpikeResult:
    prototype: str
    equity_curve: list[SpikeEquityPoint]
    trades: list[SpikeTrade]
    events: list[SpikeEvent]
    criteria: dict[str, bool | str]
    implementation_lines: int
    determinism_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "determinism_hash", _stable_hash(self))


@dataclass
class _Position:
    lots: int = 0
    avg_price: float = 0.0
    contract: str = ""


def run_purpose_built_spike(panel: Any, config: SpikeConfig) -> SpikeResult:
    """Run a minimal daily futures book simulator over a PanelData-like object."""
    dates = _selected_dates(panel.calendar, config.start, config.end)
    positions: dict[str, _Position] = {instrument: _Position() for instrument in config.instruments}
    cash = float(config.initial_cash_rmb)
    trades: list[SpikeTrade] = []
    events: list[SpikeEvent] = []
    equity_curve: list[SpikeEquityPoint] = []

    if len(dates) < 2:
        raise ValueError("spike requires at least two panel dates")

    rebalance_date = dates[0]
    fill_date = dates[1]
    fill_view = panel.view(fill_date)
    for instrument in config.instruments:
        target = int(config.target_lots.get(instrument, 0))
        current = positions[instrument].lots
        diff = target - current
        if diff == 0:
            continue
        bar = fill_view.bars(instrument, 1).iloc[-1]
        meta = fill_view.meta(instrument)
        intended = float(bar["open"])
        fill_price = _slipped_price(intended, diff, config.slippage_bps, float(meta.tick))
        commission = _commission_rmb(meta, fill_price, abs(diff))
        cash -= commission
        positions[instrument] = _Position(
            lots=target,
            avg_price=fill_price,
            contract=str(bar["contract"]),
        )
        trades.append(
            SpikeTrade(
                date=fill_date,
                instrument=instrument,
                contract=str(bar["contract"]),
                lots=diff,
                intended_price=round(intended, 10),
                fill_price=round(fill_price, 10),
                slippage_rmb=round(abs(fill_price - intended) * abs(diff) * float(meta.multiplier), 10),
                commission_rmb=round(commission, 10),
            )
        )

    for date in dates:
        view = panel.view(date)
        margin = _margin_used(view, positions)
        equity = cash + _unrealized_pnl(view, positions)
        if margin > equity:
            events.append(
                SpikeEvent(
                    date=date,
                    type="forced_liquidation",
                    detail={"margin_used_rmb": round(margin, 10), "equity_rmb": round(equity, 10)},
                )
            )
            positions = {instrument: _Position() for instrument in config.instruments}
            margin = 0.0
            equity = cash
        equity_curve.append(
            SpikeEquityPoint(
                date=date,
                equity_rmb=round(equity, 10),
                cash_rmb=round(cash, 10),
                margin_used_rmb=round(margin, 10),
            )
        )

    return SpikeResult(
        prototype="purpose_built_daily",
        equity_curve=equity_curve,
        trades=trades,
        events=events,
        criteria={
            "one_cash_account": True,
            "per_instrument_margin": True,
            "forced_liquidation": True,
            "deterministic": True,
        },
        implementation_lines=150,
    )


def run_backtrader_multidata_spike(panel: Any, config: SpikeConfig) -> SpikeResult:
    """Run a minimal direct-Backtrader multi-data prototype."""
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(config.initial_cash_rmb)
    for instrument in config.instruments:
        frame = _panel_bars_frame(panel, instrument, config.start, config.end)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=instrument)
    _TargetOnceStrategy.trades = []
    cerebro.addstrategy(_TargetOnceStrategy, target_lots=dict(config.target_lots))
    cerebro.run()

    trades = [
        SpikeTrade(
            date=trade["date"],
            instrument=trade["instrument"],
            contract="",
            lots=trade["lots"],
            intended_price=trade["price"],
            fill_price=trade["price"],
            slippage_rmb=0.0,
            commission_rmb=0.0,
        )
        for trade in _TargetOnceStrategy.trades
    ]
    last_date = _selected_dates(panel.calendar, config.start, config.end)[-1]
    result = SpikeResult(
        prototype="backtrader_multidata",
        equity_curve=[
            SpikeEquityPoint(
                date=last_date,
                equity_rmb=round(float(cerebro.broker.getvalue()), 10),
                cash_rmb=round(float(cerebro.broker.getcash()), 10),
                margin_used_rmb=0.0,
            )
        ],
        trades=trades,
        events=[],
        criteria={
            "one_cash_account": True,
            "per_instrument_margin": False,
            "forced_liquidation": False,
            "deterministic": True,
            "contract_aware_multidata_wrapper": "not proven; existing wrapper is single-instrument oriented",
        },
        implementation_lines=95,
    )
    return result


class _TargetOnceStrategy(bt.Strategy):
    params = (("target_lots", None),)
    trades: list[dict[str, Any]] = []

    def __init__(self) -> None:
        self._submitted = False

    def next(self) -> None:
        if self._submitted:
            return
        self._submitted = True
        for data in self.datas:
            instrument = data._name
            target = int(self.params.target_lots.get(instrument, 0))
            if target:
                self.order_target_size(data=data, target=target)

    def notify_order(self, order: bt.Order) -> None:
        if order.status != order.Completed:
            return
        self.trades.append(
            {
                "date": bt.num2date(order.executed.dt).date(),
                "instrument": order.data._name,
                "lots": int(order.executed.size),
                "price": round(float(order.executed.price), 10),
            }
        )


def _selected_dates(calendar: Sequence[dt.date], start: dt.date, end: dt.date) -> list[dt.date]:
    dates = [date for date in calendar if start <= date <= end]
    if not dates:
        raise ValueError("no panel dates in requested spike window")
    return dates


def _panel_bars_frame(panel: Any, instrument: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for date in _selected_dates(panel.calendar, start, end):
        rows.append(panel.view(date).bars(instrument, 1))
    frame = pd.concat(rows).sort_index()
    frame.index = pd.to_datetime(frame.index)
    return frame[["open", "high", "low", "close", "volume"]]


def _slipped_price(price: float, lots: int, slippage_bps: float, tick: float) -> float:
    direction = 1.0 if lots > 0 else -1.0
    raw = price * (1.0 + direction * slippage_bps / 10_000.0)
    return round(raw / tick) * tick if tick > 0 else raw


def _commission_rmb(meta: Any, price: float, lots_abs: int) -> float:
    if meta.commission_type == "percentage":
        return float(meta.commission) * price * float(meta.multiplier) * lots_abs
    return float(meta.commission) * lots_abs


def _margin_used(view: Any, positions: Mapping[str, _Position]) -> float:
    total = 0.0
    for instrument, position in positions.items():
        if position.lots == 0:
            continue
        bar = view.bars(instrument, 1).iloc[-1]
        meta = view.meta(instrument)
        total += abs(position.lots) * float(bar["settle"]) * float(meta.multiplier) * float(meta.margin_rate)
    return round(total, 10)


def _unrealized_pnl(view: Any, positions: Mapping[str, _Position]) -> float:
    total = 0.0
    for instrument, position in positions.items():
        if position.lots == 0:
            continue
        bar = view.bars(instrument, 1).iloc[-1]
        meta = view.meta(instrument)
        total += position.lots * (float(bar["settle"]) - position.avg_price) * float(meta.multiplier)
    return round(total, 10)


def _stable_hash(result: SpikeResult) -> str:
    payload = {
        "prototype": result.prototype,
        "equity_curve": [asdict(row) for row in result.equity_curve],
        "trades": [asdict(row) for row in result.trades],
        "events": [asdict(row) for row in result.events],
        "criteria": result.criteria,
        "implementation_lines": result.implementation_lines,
    }
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
