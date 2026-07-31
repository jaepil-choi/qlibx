from __future__ import annotations

import pandas as pd


def apply(values: pd.DataFrame, *, span: int = 5) -> pd.DataFrame:
    return values.ewm(span=span, adjust=False).mean().where(values.notna())
