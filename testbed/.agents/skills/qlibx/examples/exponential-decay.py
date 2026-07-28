"""Project-local signal_transform v1 example."""

from __future__ import annotations

import pandas as pd


def apply(values: pd.DataFrame, *, span: int = 5) -> pd.DataFrame:
    if span < 1:
        raise ValueError("span must be positive")
    result = values.ewm(span=span, adjust=False, min_periods=1).mean()
    return result.where(values.notna())
