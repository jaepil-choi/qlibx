"""
carry_z_3m — rolling z-score of carry_front_back over ~3 months
================================================================

Detects carry-regime shifts. The raw ``carry_front_back`` indicates
direction; the z-score over a 63-trading-day window (~3 calendar months)
indicates whether the curve is in an unusually strong backwardation /
contango regime.

Formula::

    mu     = mean(carry_history, window=DEFAULT_Z_WINDOW)
    sigma  = std (carry_history, window=DEFAULT_Z_WINDOW)
    z      = (carry_today - mu) / sigma

Per qorka pool metadata ``lookback=63``, ``scale_hint='z_score'``.

The function signature takes the trailing carry-series rather than
recomputing it internally — pure z-score op, stateless. Caller is
responsible for building the carry history (e.g., by calling
``carry_front_back`` on each historical snapshot).
"""
from __future__ import annotations

import pandas as pd

from .utils import DEFAULT_Z_WINDOW


def carry_z_3m(
    carry_history: pd.Series,
    window: int = DEFAULT_Z_WINDOW,
) -> float:
    """Rolling z-score of carry over a ~3-month window.

    Args:
        carry_history: Trailing series of ``carry_front_back`` values,
            *including the current day*. The last entry is treated as
            "today"; the trailing ``window - 1`` entries plus today form
            the z-score's reference distribution.
        window: Rolling window in trading days. Default 63 (~3 months).

    Returns:
        Float z-score. Positive = carry is unusually high vs its
        3-month history; negative = unusually low.

    Raises:
        ValueError: ``carry_history`` has fewer than ``window`` entries,
            or rolling stddev is zero / non-finite (flat-line carry).
    """
    if len(carry_history) < window:
        raise ValueError(
            f"carry_z_3m: carry_history has {len(carry_history)} entries, "
            f"need >= window = {window}"
        )

    tail = carry_history.astype(float).tail(window)
    mu = float(tail.mean())
    sigma = float(tail.std(ddof=1))
    # `>0` alone passes for ~3e-17 (float noise on a numerically-constant
    # series), then divides today-mu by it and produces astronomical z-
    # scores. Anchor the threshold at a tiny but non-degenerate floor so
    # flat-history is caught.
    _SIGMA_FLOOR = 1e-12
    if not (sigma > _SIGMA_FLOOR):
        raise ValueError(
            f"carry_z_3m: rolling stddev = {sigma!r} (non-positive / "
            f"sub-floor {_SIGMA_FLOOR!r}); carry history is constant — "
            "z-score undefined"
        )

    today = float(carry_history.iloc[-1])
    return (today - mu) / sigma
