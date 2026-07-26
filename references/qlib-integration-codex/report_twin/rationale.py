from __future__ import annotations

import numpy as np
import pandas as pd

from .common import (
    TRADING_DAYS,
    alpha_returns,
    combine_dynamic,
    combine_static,
    linear_decay,
    turnover_and_cost,
)
from .contract import (
    CONSENSUS_MEMBERS,
    FAMILY_NAMES,
    FINANCIAL_MEMBERS,
    MARKET_PRICE_MEMBERS,
    RATIONALE_METHODS,
    TOLERANCE,
)


LOOKBACK = 63
REBALANCE_INTERVAL = 21
FAMILY_CAP = 0.60


def build_families(members: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    price = combine_static(
        {name: members[name] for name in MARKET_PRICE_MEMBERS},
        {name: 0.25 for name in MARKET_PRICE_MEMBERS},
    )
    market = combine_static(
        {
            "free_float": members["high_free_float_ratio"],
            "price": linear_decay(price),
        },
        {"free_float": 18.0 / 23.0, "price": 5.0 / 23.0},
    )
    financial_allocation = {
        "high_leverage": 0.25,
        "high_inventory_intensity": 0.25,
        "low_depreciation_intensity": 0.25,
        "low_lease_liability_intensity": 0.125,
        "slow_low_lease_liability_intensity": 0.125,
    }
    financial = combine_static(
        {name: members[name] for name in FINANCIAL_MEMBERS},
        financial_allocation,
    )
    consensus_raw = combine_static(
        {name: members[name] for name in CONSENSUS_MEMBERS},
        {name: 1.0 / len(CONSENSUS_MEMBERS) for name in CONSENSUS_MEMBERS},
    )
    families = {
        "market_family": market,
        "financial_family": financial,
        "consensus_revision_family": linear_decay(consensus_raw),
    }
    if tuple(families) != FAMILY_NAMES:
        raise RuntimeError("family order differs from the report contract")
    return families


def build_family_history(
    families: dict[str, pd.DataFrame], realized: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gross: dict[str, pd.Series] = {}
    net: dict[str, pd.Series] = {}
    turnover: dict[str, pd.Series] = {}
    for name, weight in families.items():
        diagnostics = turnover_and_cost(weight)
        gross[name] = alpha_returns(weight, realized)
        net[name] = gross[name] - diagnostics["trade_cost"]
        turnover[name] = diagnostics["gross_turnover"]
    return pd.DataFrame(gross), pd.DataFrame(net), pd.DataFrame(turnover)


def build_rationale_candidates(
    families: dict[str, pd.DataFrame],
    family_net_return: pd.DataFrame,
    family_turnover: pd.DataFrame,
    benchmark: pd.DataFrame,
    realized: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame]:
    allocations = build_rationale_allocations(family_net_return, family_turnover)
    candidates: dict[str, pd.DataFrame] = {}
    multipliers: dict[str, pd.Series] = {}
    for method, allocation in allocations.items():
        score = combine_dynamic(families, allocation)
        screened = negative_screen(score, benchmark)
        multiplier = causal_risk_multiplier(alpha_returns(screened, realized))
        candidate = screened.mul(multiplier, axis=0).astype("float64")
        _validate_candidate(candidate, method)
        candidates[method] = candidate
        multipliers[method] = multiplier
    return candidates, allocations, pd.DataFrame(multipliers)


def build_rationale_allocations(
    family_net_return: pd.DataFrame, family_turnover: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    lagged = family_net_return.shift(1)
    volatility = lagged.rolling(LOOKBACK, min_periods=LOOKBACK).std(ddof=1)
    mean = lagged.rolling(LOOKBACK, min_periods=LOOKBACK).mean()
    turnover = family_turnover.shift(1).rolling(LOOKBACK, min_periods=LOOKBACK).mean()
    equal = pd.DataFrame(
        1.0 / len(FAMILY_NAMES),
        index=family_net_return.index,
        columns=family_net_return.columns,
    )
    risk_adjusted = mean.div(volatility.where(volatility.gt(0.0)))
    raw = {
        "rationale_equal_weight": equal,
        "rationale_inverse_volatility": volatility.where(volatility.gt(0.0)).rdiv(1.0),
        "rationale_inverse_turnover": turnover.where(turnover.gt(TOLERANCE)).rdiv(1.0),
        "rationale_risk_adjusted_momentum_rank": risk_adjusted.rank(
            axis=1, method="average", ascending=True
        ),
        "rationale_cost_aware_risk_parity": (
            volatility * np.sqrt(turnover.where(turnover.gt(TOLERANCE)))
        ).where(lambda value: value.gt(0.0)).rdiv(1.0),
    }
    result = {name: monthly_capped(value, equal) for name, value in raw.items()}
    if tuple(result) != RATIONALE_METHODS:
        raise RuntimeError("rationale method order differs")
    return result


def monthly_capped(raw: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    rows = [_normalize_and_cap(raw.iloc[position]) for position in range(len(raw))]
    normalized = pd.DataFrame(rows, index=raw.index, columns=raw.columns)
    invalid = ~np.isfinite(normalized.to_numpy()).all(axis=1)
    normalized.loc[invalid] = fallback.loc[invalid]
    decision = np.arange(len(raw)) % REBALANCE_INTERVAL == 0
    normalized.loc[~decision, :] = np.nan
    held = normalized.ffill().fillna(fallback).astype("float64")
    _validate_family_allocation(held)
    return held


def negative_screen(score: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    exclusions: set[str] = set()
    rows: list[pd.Series] = []
    for position, date in enumerate(score.index):
        current_benchmark = benchmark.loc[date].fillna(0.0).astype("float64")
        if position % REBALANCE_INTERVAL == 0:
            eligible = current_benchmark.gt(0.0) & score.loc[date].notna()
            ranked = pd.DataFrame(
                {
                    "ticker": score.columns[eligible],
                    "score": score.loc[date, eligible].to_numpy(dtype="float64"),
                }
            ).sort_values(["score", "ticker"], kind="mergesort")
            count = max(1, int(np.floor(len(ranked) * 0.10)))
            exclusions = set(ranked.iloc[:count]["ticker"].astype(str))
        screened = current_benchmark.copy()
        screened.loc[screened.index.intersection(exclusions)] = 0.0
        screened /= float(screened.sum())
        rows.append((screened - current_benchmark).rename(date))
    result = pd.DataFrame(rows, index=score.index, columns=score.columns)
    if not np.allclose(result.sum(axis=1), 0.0, atol=TOLERANCE):
        raise RuntimeError("negative-screen alpha is not self-financing")
    return result.astype("float64")


def causal_risk_multiplier(unsized_return: pd.Series) -> pd.Series:
    volatility = (
        unsized_return.shift(1).rolling(LOOKBACK, min_periods=LOOKBACK).std(ddof=1)
        * np.sqrt(TRADING_DAYS)
    )
    raw = (0.03 / volatility.where(volatility.gt(0.0))).clip(lower=0.0, upper=1.0)
    decision = pd.Series(
        np.arange(len(raw)) % REBALANCE_INTERVAL == 0, index=raw.index
    )
    return raw.where(decision).ffill().fillna(0.0).astype("float64")


def _normalize_and_cap(row: pd.Series) -> np.ndarray:
    values = row.to_numpy(dtype="float64").copy()
    if not np.isfinite(values).all() or (values < 0.0).any() or values.sum() <= 0.0:
        return np.repeat(np.nan, len(values))
    values /= values.sum()
    for _ in range(20):
        above = values > FAMILY_CAP + TOLERANCE
        if not above.any():
            break
        excess = float((values[above] - FAMILY_CAP).sum())
        values[above] = FAMILY_CAP
        below = ~above
        values[below] += excess * values[below] / float(values[below].sum())
    return values / values.sum()


def _validate_family_allocation(allocation: pd.DataFrame) -> None:
    values = allocation.to_numpy(dtype="float64")
    if not np.isfinite(values).all() or (values < -TOLERANCE).any():
        raise RuntimeError("invalid rationale family allocation")
    if (values > FAMILY_CAP + TOLERANCE).any():
        raise RuntimeError("rationale family cap exceeded")
    if not np.allclose(allocation.sum(axis=1), 1.0, atol=TOLERANCE):
        raise RuntimeError("rationale family allocation does not sum to one")


def _validate_candidate(candidate: pd.DataFrame, label: str) -> None:
    if not np.isfinite(candidate.to_numpy()).all():
        raise RuntimeError(f"non-finite rationale candidate: {label}")
    if not np.allclose(candidate.sum(axis=1), 0.0, atol=TOLERANCE):
        raise RuntimeError(f"rationale candidate is not self-financing: {label}")
