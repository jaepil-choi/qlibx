"""Cost, margin, delivery-window, and liquidity spread primitives."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from echolon.markets.expiry import days_to_last_trade, days_to_position_close
from echolon.markets.shfe.trading_calendar import TradingCalendar
from echolon.panel.models import InstrumentMeta

LIQUIDITY_LOOKBACK_TRADING_DAYS = 20


class SpreadSpec(BaseModel):
    """A same-instrument calendar spread; ``ratio`` is far lots per near lot."""

    instrument: str
    near_contract: str
    far_contract: str
    ratio: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def _different_legs(self) -> "SpreadSpec":
        if self.near_contract.upper() == self.far_contract.upper():
            raise ValueError("near_contract and far_contract must differ")
        return self


class SpreadPosition(BaseModel):
    """Signed whole-lot holdings for the near and far legs."""

    lots_near: int
    lots_far: int


class SpreadCost(BaseModel):
    """One-spread round-trip costs in RMB."""

    commission_rmb: float
    slippage_rmb: float
    total_rmb: float


class _ContractsHistoryView(Protocol):
    def contracts_history(self, instrument: str, lookback: int) -> pd.DataFrame: ...


def round_trip_cost_rmb(
    spread: SpreadSpec,
    near_price: float,
    far_price: float,
    meta: InstrumentMeta,
) -> SpreadCost:
    """Return both-leg, both-side commission plus one adverse tick per fill.

    Prices must be positive RMB per quoted unit. Unsupported commission types
    and invalid prices fail with :class:`ValueError`.
    """
    _require_prices(near_price, far_price)
    near_lots = 1.0
    far_lots = float(spread.ratio)
    commission = 2.0 * (
        _one_side_commission_rmb(meta, near_price, near_lots)
        + _one_side_commission_rmb(meta, far_price, far_lots)
    )
    slippage = 2.0 * (near_lots + far_lots) * float(meta.tick) * float(meta.multiplier)
    return SpreadCost(
        commission_rmb=commission,
        slippage_rmb=slippage,
        total_rmb=commission + slippage,
    )


def margin_required_rmb(
    spread: SpreadSpec,
    near_price: float,
    far_price: float,
    meta: InstrumentMeta,
    *,
    offset_margin: float | None = None,
) -> float:
    """Return conservative one-spread margin in RMB.

    ``offset_margin=None`` means unknown broker terms and returns the sum of
    both leg margins. A supplied broker offset is used verbatim after a
    non-negative validation; no offset is inferred.
    """
    _require_prices(near_price, far_price)
    if offset_margin is not None:
        if offset_margin < 0:
            raise ValueError("offset_margin must be non-negative")
        return float(offset_margin)
    return (
        (near_price + far_price * float(spread.ratio))
        * float(meta.multiplier)
        * float(meta.margin_rate)
    )


def tradable_window(
    spread: SpreadSpec,
    asof: dt.date,
    *,
    exchange: str,
    calendar: TradingCalendar,
) -> bool:
    """Return false within five trading days of the near-leg close boundary.

    SHFE uses its explicit position-close date; exchanges without one use
    last trade. A loaded exchange calendar is mandatory and failures propagate.
    """
    position_days = days_to_position_close(
        spread.near_contract, exchange, asof, calendar
    )
    remaining = (
        position_days
        if position_days is not None
        else days_to_last_trade(spread.near_contract, exchange, asof, calendar)
    )
    return remaining > 5


def legs_liquid(
    spread: SpreadSpec,
    view: _ContractsHistoryView,
    min_volume_lots: float,
) -> bool:
    """Screen both legs on their 20-session median daily volume in lots.

    Missing contracts, missing/non-numeric volume, and empty histories fail
    closed. ``min_volume_lots`` must be non-negative.
    """
    if min_volume_lots < 0:
        raise ValueError("min_volume_lots must be non-negative")
    history = view.contracts_history(spread.instrument, LIQUIDITY_LOOKBACK_TRADING_DAYS)
    if not {"contract", "volume"}.issubset(history.columns):
        return False
    contract_ids = history["contract"].astype(str).str.upper()
    volumes = pd.to_numeric(history["volume"], errors="coerce")
    medians: list[float] = []
    for contract in (spread.near_contract, spread.far_contract):
        leg = volumes.loc[contract_ids == contract.upper()].dropna()
        if leg.empty:
            return False
        medians.append(float(leg.median()))
    return all(median >= min_volume_lots for median in medians)


def _one_side_commission_rmb(
    meta: InstrumentMeta,
    price: float,
    lots: float,
) -> float:
    if meta.commission_type == "percentage":
        return price * float(meta.multiplier) * lots * float(meta.commission)
    if meta.commission_type == "per_contract":
        return lots * float(meta.commission)
    raise ValueError(f"unsupported commission_type: {meta.commission_type}")


def _require_prices(near_price: float, far_price: float) -> None:
    if near_price <= 0 or far_price <= 0:
        raise ValueError("leg prices must be positive RMB values")
