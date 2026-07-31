"""
carry_change_20d — 20-trading-day change in carry_front_back
=============================================================

Momentum-flavored carry indicator. Captures recent dynamics: did the
curve steepen (carry rising) or flatten (carry falling) over the last
20 trading days?

Formula::

    change_20d = carry_history[-1] - carry_history[-1 - lag]
               = carry_today - carry_(t-20)

Per qorka pool metadata ``lookback=20``, ``scale_hint='delta'``.

Complementary to ``carry_z_3m``: change captures recent dynamics,
z captures distributional position. The two combine well in a regime-
filtered entry (only enter when both change + z point the same way).

Stateless — takes the trailing carry-series and returns a scalar delta.
"""
from __future__ import annotations

import pandas as pd

from .utils import DEFAULT_CHANGE_LAG


def carry_change_20d(
    carry_history: pd.Series,
    lag: int = DEFAULT_CHANGE_LAG,
) -> float:
    """20-day change in carry_front_back.

    Args:
        carry_history: Trailing series of ``carry_front_back`` values,
            *including the current day* as the last entry. Must have
            at least ``lag + 1`` entries.
        lag: Lookback lag in trading days. Default 20.

    Returns:
        Float — carry_today minus carry_(t - lag). Sign convention
        follows ``carry_front_back``: positive = backwardation has
        strengthened (or contango has weakened) over the lag window.

    Raises:
        ValueError: ``carry_history`` has fewer than ``lag + 1`` entries.
    """
    if len(carry_history) < lag + 1:
        raise ValueError(
            f"carry_change_20d: carry_history has {len(carry_history)} "
            f"entries, need >= lag + 1 = {lag + 1}"
        )

    today = float(carry_history.iloc[-1])
    past = float(carry_history.iloc[-1 - lag])
    return today - past
