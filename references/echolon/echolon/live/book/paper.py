"""Paper-fill arithmetic shared with the certified book backtester.

Paper trading must measure the SAME cost model the release bundle was
certified under. These helpers delegate to the daily book backtester's
fill/commission/position arithmetic so the paper path cannot drift from
the backtest cost model — one implementation, two callers.

Fill convention (paper contract): orders submitted after close on day T
fill at day T+1's open ± ``slippage_bps`` (tick-rounded), exactly like the
backtester's next-session-open fills.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from echolon.backtest.book.accounting import commission_rmb
from echolon.backtest.book.engine import (  # single source of truth for position arithmetic
    _Position,
    _realized_pnl,
    _slipped_price,
    _updated_position,
)
from echolon.panel.models import InstrumentMeta


@dataclass(frozen=True)
class PaperPosition:
    """Simulated held position for one instrument."""

    lots: int = 0
    avg_price: float = 0.0
    contract: str = ""


@dataclass(frozen=True)
class PaperFill:
    """Result of simulating one order fill at next-session open."""

    fill_price: float
    slippage_rmb: float
    commission_rmb: float
    realized_pnl_rmb: float
    position_after: PaperPosition


def simulate_paper_fill(
    *,
    position: PaperPosition,
    lots_delta: int,
    open_price: float,
    contract: str,
    meta: InstrumentMeta,
    slippage_bps: float,
    fill_date: "dt.date | None" = None,
    close_today: bool = False,
) -> PaperFill:
    """Fill ``lots_delta`` signed lots at ``open_price`` + slippage.

    Uses the backtester's exact arithmetic for slipped price, commission
    (incl. close-today 平今 treatment), realized PnL, and position update.
    """
    if lots_delta == 0:
        raise ValueError("lots_delta must be non-zero")
    engine_position = _Position(
        lots=float(position.lots), avg_price=position.avg_price, contract=position.contract
    )
    fill_price = _slipped_price(float(open_price), lots_delta, float(slippage_bps), float(meta.tick))
    commission = commission_rmb(
        meta, fill_price, abs(lots_delta), close_today=close_today
    )
    realized = _realized_pnl(engine_position, lots_delta, fill_price, float(meta.multiplier))
    updated = _updated_position(engine_position, lots_delta, fill_price, contract, date=fill_date)
    return PaperFill(
        fill_price=fill_price,
        slippage_rmb=abs(fill_price - float(open_price)) * abs(lots_delta) * float(meta.multiplier),
        commission_rmb=commission,
        realized_pnl_rmb=realized,
        position_after=PaperPosition(
            lots=int(updated.lots),
            avg_price=updated.avg_price,
            contract=updated.contract,
        ),
    )


def unrealized_pnl_rmb(position: PaperPosition, settle: float, meta: InstrumentMeta) -> float:
    """Mark-to-settle unrealized PnL for one simulated position."""
    if position.lots == 0:
        return 0.0
    return position.lots * (float(settle) - position.avg_price) * float(meta.multiplier)


def margin_used_rmb(position: PaperPosition, settle: float, meta: InstrumentMeta) -> float:
    """Margin consumed by one simulated position at the given settle."""
    if position.lots == 0:
        return 0.0
    return abs(position.lots) * float(settle) * float(meta.multiplier) * float(meta.margin_rate)
