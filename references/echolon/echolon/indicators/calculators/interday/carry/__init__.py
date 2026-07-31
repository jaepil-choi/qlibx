"""
Carry indicator pool (Gate 1C WS2 B2.3)
========================================

Forward-curve-based carry indicators for SHFE metals (and any other
multi-contract futures market exposed through
:func:`echolon.data.loaders.chain_composer.get_curve_snapshot`).

The five canonical names (LOAD-BEARING — must match qorka-side names
byte-equal per ``paradigms/carry/indicator_pool.py::CARRY_POOL_METADATA``):

- :func:`carry_front_back`   — annualized front-vs-back basis (PRIMARY signal)
- :func:`curve_slope_near`   — log-settlement regression slope across n=3 near contracts
- :func:`risk_adj_carry`     — carry_front_back / realized-vol (vol-normalized)
- :func:`carry_z_3m`         — rolling z-score of carry over ~63 trading days
- :func:`carry_change_20d`   — 20-day delta in carry_front_back

Signature contract — these are NOT TA-Lib-style ``(df, timeperiod) -> ndarray``
calculators (their inputs span multiple contracts and rolling histories),
so they are intentionally NOT registered in
``echolon.indicators.calculators.interday.indicator_mapping.INDICATOR_MAPPING``.
The qorka strategy layer imports them by name from this package:

    from echolon.indicators.calculators.interday.carry import (
        carry_front_back,
        curve_slope_near,
        risk_adj_carry,
        carry_z_3m,
        carry_change_20d,
    )

Sign convention (uniform across all 5): positive = backwardation =
long-side carry; negative = contango = short-side. The signal value is
what the qorka sizer reads to set direction + signal_strength.
"""
from __future__ import annotations

from .carry_change_20d import carry_change_20d
from .carry_front_back import carry_front_back
from .carry_z_3m import carry_z_3m
from .curve_slope_near import curve_slope_near
from .risk_adj_carry import risk_adj_carry
from .utils import (
    DEFAULT_CHANGE_LAG,
    DEFAULT_SLOPE_N,
    DEFAULT_VOL_WINDOW,
    DEFAULT_Z_WINDOW,
    extract_settlement,
    front_back_settlements,
)

__all__ = [
    "carry_front_back",
    "curve_slope_near",
    "risk_adj_carry",
    "carry_z_3m",
    "carry_change_20d",
    # Shared helpers (used by tests and qorka strategy code that
    # builds carry-history series outside this package).
    "extract_settlement",
    "front_back_settlements",
    "DEFAULT_VOL_WINDOW",
    "DEFAULT_Z_WINDOW",
    "DEFAULT_CHANGE_LAG",
    "DEFAULT_SLOPE_N",
]
