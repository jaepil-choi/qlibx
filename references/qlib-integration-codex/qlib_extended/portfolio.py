from __future__ import annotations

import numpy as np
import pandas as pd


def build_long_only_targets(
    alpha: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    signal_lag: int,
    top_n: int,
    gross_exposure: float,
) -> pd.DataFrame:
    """Convert an alpha matrix to explicit long-only physical target weights."""

    if not alpha.index.equals(universe.index) or not alpha.columns.equals(universe.columns):
        raise ValueError("alpha and universe axes must match")
    if signal_lag < 0 or top_n <= 0 or not 0 < gross_exposure <= 1:
        raise ValueError("invalid portfolio construction parameters")
    targets = pd.DataFrame(0.0, index=alpha.index, columns=alpha.columns)
    for date in alpha.index:
        eligible = universe.loc[date].astype(bool) & alpha.loc[date].map(np.isfinite)
        ranked = alpha.loc[date, eligible].nlargest(top_n)
        if ranked.empty:
            continue
        targets.loc[date, ranked.index] = gross_exposure / len(ranked)
    if signal_lag:
        targets = targets.shift(signal_lag, fill_value=0.0)
    return targets.astype("float64")
