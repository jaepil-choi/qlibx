from __future__ import annotations

import pandas as pd


def signed_momentum(returns: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    score = returns.astype("float64").rolling(5, min_periods=5).mean().where(universe)
    ranks = score.rank(axis=1, pct=True)
    long_mask = ranks.ge(0.95)
    short_mask = ranks.le(0.05)
    long_count = long_mask.sum(axis=1).replace(0, pd.NA).astype("Float64")
    short_count = short_mask.sum(axis=1).replace(0, pd.NA).astype("Float64")
    alpha = long_mask.div(long_count, axis=0).fillna(0.0) * 0.20
    alpha -= short_mask.div(short_count, axis=0).fillna(0.0) * 0.20
    return alpha.astype("float64")
