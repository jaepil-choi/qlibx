from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .contract import TOLERANCE


TRADING_DAYS = 252
BUY_RATE = 0.0003
SELL_RATE = 0.0003
SELL_TAX = 0.0020


def combine_static(
    frames: Mapping[str, pd.DataFrame], weights: Mapping[str, float]
) -> pd.DataFrame:
    if set(frames) != set(weights) or not np.isclose(sum(weights.values()), 1.0):
        raise ValueError("static ensemble members and unit-sum weights must match")
    first = next(iter(frames.values()))
    result = first * 0.0
    for name, frame in frames.items():
        _same_axes(first, frame, name)
        result = result.add(frame * float(weights[name]))
    return result.astype("float64")


def combine_dynamic(
    frames: Mapping[str, pd.DataFrame], allocation: pd.DataFrame
) -> pd.DataFrame:
    if set(frames) != set(allocation.columns):
        raise ValueError("dynamic allocation columns must match ensemble members")
    values = allocation.to_numpy(dtype="float64")
    if not np.isfinite(values).all() or (values < -TOLERANCE).any():
        raise ValueError("dynamic allocation must be finite and non-negative")
    if not np.allclose(allocation.sum(axis=1), 1.0, atol=TOLERANCE):
        raise ValueError("dynamic allocation rows must sum to one")
    first = next(iter(frames.values()))
    result = first * 0.0
    for name, frame in frames.items():
        _same_axes(first, frame, name)
        if not allocation.index.equals(frame.index):
            raise ValueError("dynamic allocation dates must match member dates")
        result = result.add(frame.mul(allocation[name], axis=0))
    return result.astype("float64")


def linear_decay(weight: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    if window <= 0:
        raise ValueError("decay window must be positive")
    values = weight.fillna(0.0).to_numpy(dtype="float64")
    result = np.empty_like(values)
    for position in range(len(values)):
        start = max(0, position - window + 1)
        block = values[start : position + 1]
        kernel = np.arange(1, len(block) + 1, dtype="float64")
        result[position] = (block * kernel[:, None]).sum(axis=0) / kernel.sum()
    return pd.DataFrame(result, index=weight.index, columns=weight.columns)


def alpha_returns(weight: pd.DataFrame, realized: pd.DataFrame) -> pd.Series:
    _same_axes(weight, realized, "realized_return")
    return (weight * realized.fillna(0.0)).sum(axis=1).astype("float64")


def turnover_and_cost(weight: pd.DataFrame, *, etf: bool = False) -> pd.DataFrame:
    delta = weight.diff().fillna(weight)
    buy = delta.clip(lower=0.0).sum(axis=1)
    sell = -delta.clip(upper=0.0).sum(axis=1)
    tax = 0.0 if etf else SELL_TAX
    return pd.DataFrame(
        {
            "buy_turnover": buy,
            "sell_turnover": sell,
            "gross_turnover": buy + sell,
            "trade_cost": buy * BUY_RATE + sell * (SELL_RATE + tax),
        },
        index=weight.index,
    ).astype("float64")


def annualized_mean(values: pd.Series) -> float:
    return float(values.mean() * TRADING_DAYS)


def annualized_volatility(values: pd.Series) -> float:
    return float(values.std(ddof=1) * np.sqrt(TRADING_DAYS))


def _same_axes(left: pd.DataFrame, right: pd.DataFrame, label: str) -> None:
    if not left.index.equals(right.index) or not left.columns.equals(right.columns):
        raise ValueError(f"{label} axes differ")
