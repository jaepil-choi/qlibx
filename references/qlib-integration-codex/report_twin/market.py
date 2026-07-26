from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .common import combine_dynamic
from .contract import MARKET_METHODS, MARKET_PRICE_MEMBERS, TOLERANCE


def build_market_method_weights(
    member_weights: dict[str, pd.DataFrame],
    realized_return: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    if tuple(member_weights) != MARKET_PRICE_MEMBERS:
        raise ValueError("market method members differ from the four-member contract")
    returns = pd.DataFrame(
        {
            name: (weight * realized_return.fillna(0.0)).sum(axis=1)
            for name, weight in member_weights.items()
        },
        index=realized_return.index,
    )
    allocations = {
        method: build_market_allocation(returns, method) for method in MARKET_METHODS
    }
    executable_members = {
        name: weight.fillna(0.0).astype("float64")
        for name, weight in member_weights.items()
    }
    combined = {
        method: combine_dynamic(executable_members, allocation)
        for method, allocation in allocations.items()
    }
    return allocations, combined


def build_market_allocation(returns: pd.DataFrame, method: str) -> pd.DataFrame:
    if method not in MARKET_METHODS:
        raise ValueError(f"unknown market ensemble method: {method}")
    names = tuple(returns.columns)
    fallback = {name: 1.0 / len(names) for name in names}
    rows: list[dict[str, float]] = []
    for position in range(len(returns)):
        history = returns.iloc[:position]
        rows.append(_allocation_row(method, history, fallback))
    result = pd.DataFrame(rows, index=returns.index, columns=returns.columns)
    _validate_allocation(result, method)
    return result.astype("float64")


def _allocation_row(
    method: str,
    history: pd.DataFrame,
    fallback: dict[str, float],
) -> dict[str, float]:
    if method == "equal_weight":
        return dict(fallback)
    if method == "trailing_return_momentum":
        if len(history) < 20:
            return dict(fallback)
        scores = history.iloc[-20:].mean()
        centered = scores - scores.mean()
        raw = {
            name: fallback[name]
            * math.exp(float(np.clip(100.0 * centered[name], -10.0, 10.0)))
            for name in history.columns
        }
        return _normalize_mapping(raw)
    if method == "trailing_return_rank":
        if len(history) < 20:
            return dict(fallback)
        ranks = history.iloc[-20:].mean().rank(method="average", ascending=True)
        return _normalize_series(ranks)
    if method == "dual_horizon_rank_momentum":
        if len(history) < 126:
            return dict(fallback)
        short = history.iloc[-20:].mean().rank(method="average", ascending=True)
        long = history.iloc[-126:].mean().rank(method="average", ascending=True)
        return _normalize_series(0.5 * short + 0.5 * long)
    if len(history) < 60:
        return dict(fallback)
    means = history.iloc[-20:].mean()
    scores: dict[str, float] = {}
    for name in history.columns:
        sample = history[name].iloc[-60:]
        if method == "risk_adjusted_return_momentum":
            risk = float(sample.std(ddof=1))
        elif method == "downside_adjusted_return_momentum":
            risk = float(np.sqrt(np.square(sample.clip(upper=0.0)).mean()))
        else:
            raise AssertionError(method)
        if not math.isfinite(risk) or risk <= 0.0:
            return dict(fallback)
        scores[name] = float(means[name]) / risk
    return _standardized_softmax(scores, fallback)


def _standardized_softmax(
    scores: dict[str, float], fallback: dict[str, float]
) -> dict[str, float]:
    series = pd.Series(scores, dtype="float64")
    centered = series - series.mean()
    scale = float(centered.std(ddof=1))
    if not math.isfinite(scale) or scale <= 0.0:
        return dict(fallback)
    raw = np.exp((centered / scale).clip(lower=-3.0, upper=3.0))
    normalized = raw / float(raw.sum())
    return _cap_and_renormalize(normalized, cap=0.55)


def _cap_and_renormalize(weights: pd.Series, *, cap: float) -> dict[str, float]:
    result = weights.astype("float64").copy()
    for _ in range(100):
        above = result.gt(cap + TOLERANCE)
        if not above.any():
            break
        excess = float((result.loc[above] - cap).sum())
        result.loc[above] = cap
        below = ~above
        available = float(result.loc[below].sum())
        if available <= 0.0:
            raise ValueError("market allocation cap has no uncapped weight")
        result.loc[below] += excess * result.loc[below] / available
    if result.gt(cap + TOLERANCE).any():
        raise RuntimeError("market allocation cap did not converge")
    result /= float(result.sum())
    return {str(name): float(value) for name, value in result.items()}


def _normalize_mapping(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    return {name: value / total for name, value in values.items()}


def _normalize_series(values: pd.Series) -> dict[str, float]:
    normalized = values / float(values.sum())
    return {str(name): float(value) for name, value in normalized.items()}


def _validate_allocation(allocation: pd.DataFrame, method: str) -> None:
    values = allocation.to_numpy(dtype="float64")
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise RuntimeError(f"invalid market allocation: {method}")
    if not np.allclose(allocation.sum(axis=1), 1.0, atol=TOLERANCE):
        raise RuntimeError(f"market allocation does not sum to one: {method}")
