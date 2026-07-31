"""
curve_slope_near — slope of log(settlement) vs days_to_expiry, near contracts
=============================================================================

Smoothed alternative to the raw two-contract basis. Fits a linear
regression of ``log(settlement)`` against ``days_to_expiry`` across the
nearest ``n`` (default 3) active contracts and returns the slope
coefficient.

Sign convention (matches ``carry_front_back``): a *negative* slope of
log-settlement vs DTE corresponds to backwardation (settlement falls as
DTE rises). To preserve "positive = backwardation = long signal", we
return ``-slope`` so the carry-pool sign convention is uniform across
all five indicators (per qorka ``paradigms/carry/indicator_pool.py``
line 14 + line 18-22 docstring).

Formula::

    fit log(settlement_i) ≈ alpha + beta * days_to_expiry_i
                            (i = 0..n-1, n near contracts)
    return -beta

Per qorka pool metadata ``scale_hint='slope'``: this is a slope-flavored
signal whose magnitude is "log-settlement per day of expiry"; downstream
sizers may want to multiply by an empirical scaling.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from echolon.indicators.calculators._utils import _require_columns

from .utils import DEFAULT_SLOPE_N


def curve_slope_near(curve_snapshot: pd.DataFrame, n: int = DEFAULT_SLOPE_N) -> float:
    """Slope of -log(settlement) vs days_to_expiry across near contracts.

    Args:
        curve_snapshot: DataFrame from
            :func:`echolon.data.loaders.chain_composer.get_curve_snapshot`.
            Must have at least 2 rows; uses up to ``n`` nearest contracts.
        n: Number of near contracts to fit through. Default 3.

    Returns:
        Slope coefficient as a float. Positive = backwardation (front >
        back, log-settlement falls with DTE). Negative = contango.

    Raises:
        EchelonError IND-005: missing ``settlement`` or
            ``days_to_expiry`` column.
        ValueError: snapshot has fewer than 2 contracts (regression
            requires 2+ points) OR any settlement <= 0 (log undefined).
    """
    _require_columns(
        curve_snapshot,
        ["settlement", "days_to_expiry"],
        calculator="curve_slope_near",
    )
    sub = curve_snapshot.head(n)
    if len(sub) < 2:
        raise ValueError(
            f"curve_slope_near: only {len(sub)} contracts available "
            f"(need >= 2 for regression)"
        )

    settlements = sub["settlement"].astype(float).values
    if np.any(settlements <= 0):
        raise ValueError(
            "curve_slope_near: non-positive settlement(s) in chain "
            f"({settlements.tolist()}); log undefined"
        )

    dte = sub["days_to_expiry"].astype(float).values
    log_settlement = np.log(settlements)

    # np.polyfit returns coefficients highest-degree-first; degree=1 →
    # [slope, intercept]. We invert the sign so positive = backwardation.
    slope, _intercept = np.polyfit(dte, log_settlement, deg=1)
    if math.isnan(slope) or math.isinf(slope):
        # Degenerate fit (e.g., all DTEs equal — variance zero). Surface
        # rather than silently return NaN.
        raise ValueError(
            "curve_slope_near: regression yielded NaN/Inf slope (likely "
            f"degenerate DTE vector: {dte.tolist()})"
        )
    return float(-slope)
