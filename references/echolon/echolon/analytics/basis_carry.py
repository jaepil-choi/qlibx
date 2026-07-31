"""Public-safe basis and annualized carry measurements.

Inputs and outputs are decimal fractions (0.02 means 2%), not percentages.
Series are aligned by their shared index; missing or invalid values remain missing.
"""
from __future__ import annotations

import pandas as pd


def basis_series(future_settle: pd.Series, index_close: pd.Series) -> pd.Series:
    """Return signed futures basis as a decimal fraction; zero spot yields NaN."""
    future, spot = future_settle.align(index_close, join="inner")
    spot = pd.to_numeric(spot, errors="coerce").replace(0.0, float("nan"))
    return (pd.to_numeric(future, errors="coerce") - spot) / spot


def annualized_carry_cost(basis: pd.Series, days_to_expiry: pd.Series) -> pd.Series:
    """Return annualized short-hedge carry cost as a decimal fraction."""
    aligned_basis, days = basis.align(days_to_expiry, join="inner")
    days = pd.to_numeric(days, errors="coerce").where(lambda values: values > 0)
    return -pd.to_numeric(aligned_basis, errors="coerce") * (365.0 / days)


def daily_hedge_carry(active_settles: pd.DataFrame, index_close: pd.Series) -> pd.DataFrame:
    """Return daily short-hedge carry cost as a decimal fraction; roll days are NaN."""
    required = {"contract", "settle"}
    missing = required.difference(active_settles.columns)
    if missing:
        raise ValueError(f"active_settles missing columns: {sorted(missing)}")
    frame = active_settles.loc[:, ["contract", "settle"]].copy()
    spot = pd.to_numeric(index_close.reindex(frame.index), errors="coerce")
    future_return = pd.to_numeric(frame["settle"], errors="coerce").pct_change()
    spot_return = spot.pct_change()
    same_contract = frame["contract"].eq(frame["contract"].shift(1))
    frame["hedge_carry_cost"] = (future_return - spot_return).where(same_contract)
    return frame.loc[:, ["contract", "hedge_carry_cost"]]
