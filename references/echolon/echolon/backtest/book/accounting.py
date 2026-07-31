"""Public deterministic accounting primitives shared by book runtimes."""
from __future__ import annotations

from typing import Any


def commission_rmb(
    meta: Any,
    price: float,
    lots_abs: float,
    *,
    close_today: bool = False,
    side: str | None = None,
    stamp_duty_rate_override: float | None = None,
) -> float:
    """Return one fill's complete RMB fee from explicit instrument metadata."""
    commission = (
        float(meta.close_today_commission)
        if close_today and meta.close_today_commission is not None
        else float(meta.commission)
    )
    notional = price * float(meta.multiplier) * lots_abs
    brokerage = (
        commission * notional
        if meta.commission_type == "percentage"
        else commission * lots_abs
    )
    if side is None:
        return brokerage
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY, SELL, or None")
    brokerage = max(brokerage, float(meta.min_commission))
    duty_rate = (
        float(meta.stamp_duty_rate)
        if stamp_duty_rate_override is None
        else float(stamp_duty_rate_override)
    )
    stamp_duty = notional * duty_rate if side == "SELL" else 0.0
    return brokerage + stamp_duty + notional * float(meta.transfer_fee_rate)
