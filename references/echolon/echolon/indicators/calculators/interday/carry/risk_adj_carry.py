"""
risk_adj_carry — carry_front_back normalized by realized volatility
====================================================================

Volatility-normalized carry signal. The standard quant-CTA construct:
divide the instantaneous carry by recent realized volatility so that
cross-instrument carry magnitudes are comparable on a per-unit-of-risk
basis.

Formula::

    rolling_vol = stddev(daily_returns(front_settlement_series),
                         window=DEFAULT_VOL_WINDOW)
    risk_adj    = carry_front_back(curve_snapshot) / rolling_vol_today

Per qorka pool metadata ``lookback=20``, ``scale_hint='signed_ratio'``.

Implementation note: the realized-vol denominator is computed on the
*front-contract* daily settlement returns. The caller passes a history
series — typically the trailing ``DEFAULT_VOL_WINDOW + buffer`` days of
front-contract settlements assembled by walking
``chain_composer.get_curve_snapshot`` (or any equivalent path that
extracts the active front settlement on each historical date).

The function signature deliberately takes ``front_settlement_series``
as a pd.Series rather than re-computing the vol internally — keeps the
indicator stateless and makes vol-source choice (raw vs deseasonalized,
log-return vs simple) explicit at the caller.
"""
from __future__ import annotations

import pandas as pd

from .carry_front_back import carry_front_back
from .utils import DEFAULT_VOL_WINDOW


def risk_adj_carry(
    curve_snapshot: pd.DataFrame,
    front_settlement_series: pd.Series,
    window: int = DEFAULT_VOL_WINDOW,
) -> float:
    """Volatility-normalized carry.

    Args:
        curve_snapshot: Same-date forward-curve snapshot (from
            :func:`echolon.data.loaders.chain_composer.get_curve_snapshot`).
            Used to compute the numerator via ``carry_front_back``.
        front_settlement_series: Trailing series of front-contract
            daily settlement values, *including the current day*.
            Must have at least ``window + 1`` entries so we can take
            ``window`` daily returns.
        window: Rolling-stddev window in trading days. Default 20.

    Returns:
        Float — carry per unit of realized vol. Same sign convention as
        ``carry_front_back``.

    Raises:
        Any error raised by ``carry_front_back``.
        ValueError: ``front_settlement_series`` is too short for the
            requested window, or computed vol is zero/non-finite.
    """
    if len(front_settlement_series) < window + 1:
        raise ValueError(
            f"risk_adj_carry: front_settlement_series has "
            f"{len(front_settlement_series)} entries, need >= window + 1 "
            f"= {window + 1} for {window}-day return-vol"
        )

    returns = front_settlement_series.astype(float).pct_change().dropna()
    vol = float(returns.tail(window).std(ddof=1))
    # See carry_z_3m note: `>0` alone passes for ~3e-17 float noise on a
    # numerically-constant series, then divides carry by it and produces
    # astronomically large signals. Anchor at a non-degenerate floor.
    _VOL_FLOOR = 1e-12
    if not (vol > _VOL_FLOOR):
        raise ValueError(
            f"risk_adj_carry: realized vol = {vol!r} (non-positive / "
            f"sub-floor {_VOL_FLOOR!r}); front settlement series is "
            "constant or degenerate"
        )

    return carry_front_back(curve_snapshot) / vol
