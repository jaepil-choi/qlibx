from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


SUPPORTED_RULES = (
    "equal_weight",
    "inverse_volatility",
    "momentum",
    "momentum_risk",
    "minimum_variance_turnover",
    "diversification",
    "drawdown_adjusted_momentum",
    "return_to_turnover",
    "rank_momentum",
    "positive_sharpe_squared",
    "momentum_diversification",
    "cost_adjusted_momentum",
    "minimum_variance_momentum",
)


@dataclass(frozen=True)
class DynamicAllocationSpec:
    name: str
    rule: str
    rebalance_days: int = 63
    lookback_days: int = 252
    minimum_history_days: int = 126

    def __post_init__(self) -> None:
        if self.rule not in SUPPORTED_RULES:
            raise ValueError(f"Unsupported dynamic allocation rule: {self.rule}")
        if self.rebalance_days < 1:
            raise ValueError("rebalance_days must be positive.")
        if self.minimum_history_days < 2:
            raise ValueError("minimum_history_days must be at least two.")
        if self.lookback_days < self.minimum_history_days:
            raise ValueError("lookback_days must cover minimum_history_days.")


def build_causal_allocation(
    returns: pd.DataFrame,
    spec: DynamicAllocationSpec,
    *,
    turnover: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """과거 family return만 사용해 long-only allocation을 생성합니다."""
    if returns.empty or returns.shape[1] < 2:
        raise ValueError("Dynamic allocation requires at least two return series.")
    if returns.columns.has_duplicates:
        raise ValueError("Return columns must be unique.")
    if turnover is not None:
        if not turnover.index.equals(returns.index) or not turnover.columns.equals(
            returns.columns
        ):
            raise ValueError("Turnover and return axes must match.")
    clean = returns.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype("float64")
    clean_turnover = (
        turnover.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype("float64")
        if turnover is not None
        else None
    )
    member_count = clean.shape[1]
    equal = np.repeat(1.0 / member_count, member_count)
    previous = equal.copy()
    decisions: dict[int, np.ndarray] = {}
    for position in range(0, len(clean), spec.rebalance_days):
        start = max(0, position - spec.lookback_days)
        history = clean.iloc[start:position]
        turnover_history = (
            clean_turnover.iloc[start:position]
            if clean_turnover is not None
            else None
        )
        if len(history) < spec.minimum_history_days:
            weights = equal
        else:
            weights = _allocation_for_rule(
                history,
                spec.rule,
                previous=previous,
                turnover=turnover_history,
            )
        decisions[position] = weights
        previous = weights

    allocation = pd.DataFrame(
        np.nan,
        index=clean.index,
        columns=clean.columns,
        dtype="float64",
    )
    for position, weights in decisions.items():
        allocation.iloc[position] = weights
    allocation = allocation.ffill().fillna(1.0 / member_count)
    if (allocation < -1e-12).any().any():
        raise RuntimeError("Dynamic allocation produced a negative weight.")
    if not np.allclose(allocation.sum(axis=1), 1.0, atol=1e-10):
        raise RuntimeError("Dynamic allocation rows do not sum to one.")
    return allocation


def combine_targets(
    targets: Mapping[str, pd.DataFrame],
    allocation: pd.DataFrame,
) -> pd.DataFrame:
    if set(targets) != set(allocation.columns):
        raise ValueError("Target names and allocation columns must match.")
    first = next(iter(targets.values()))
    output = pd.DataFrame(0.0, index=first.index, columns=first.columns)
    for name, target in targets.items():
        if not target.index.equals(first.index) or not target.columns.equals(
            first.columns
        ):
            raise ValueError(f"Target axes do not match: {name}")
        output = output.add(target.mul(allocation[name], axis=0))
    return output


def allocation_turnover(allocation: pd.DataFrame) -> pd.Series:
    return allocation.diff().abs().sum(axis=1).fillna(0.0)


def _allocation_for_rule(
    history: pd.DataFrame,
    rule: str,
    *,
    previous: np.ndarray,
    turnover: pd.DataFrame | None,
) -> np.ndarray:
    values = history.to_numpy(dtype="float64")
    mean = values.mean(axis=0)
    volatility = values.std(axis=0, ddof=1)
    safe_volatility = np.where(volatility > 1e-12, volatility, np.nan)
    equal = np.repeat(1.0 / values.shape[1], values.shape[1])

    if rule == "equal_weight":
        return equal
    if rule == "inverse_volatility":
        return _normalize_positive(1.0 / safe_volatility, fallback=equal)
    if rule == "momentum":
        return _softmax_standardized(mean / safe_volatility, fallback=equal)
    if rule == "momentum_risk":
        positive_mean = np.clip(mean, 0.0, None)
        return _normalize_positive(
            positive_mean / np.square(safe_volatility),
            fallback=_normalize_positive(1.0 / safe_volatility, fallback=equal),
        )
    if rule == "minimum_variance_turnover":
        covariance = np.cov(values, rowvar=False, ddof=1)
        covariance = np.atleast_2d(covariance)
        diagonal = np.diag(np.diag(covariance))
        shrunk = 0.5 * covariance + 0.5 * diagonal
        # Penalty scale follows the covariance itself, so no return-period-tuned
        # lambda is introduced. It discourages needless quarterly family churn.
        penalty = float(np.trace(shrunk) / len(shrunk))
        return _minimum_variance_with_turnover(
            shrunk,
            previous=previous,
            penalty=penalty,
        )
    if rule == "diversification":
        correlation = history.corr().abs().to_numpy(dtype="float64", copy=True)
        np.fill_diagonal(correlation, 0.0)
        average_correlation = correlation.sum(axis=1) / max(1, len(correlation) - 1)
        score = (1.0 / safe_volatility) / (1.0 + average_correlation)
        return _normalize_positive(score, fallback=equal)
    if rule == "drawdown_adjusted_momentum":
        wealth = np.cumprod(1.0 + values, axis=0)
        running_peak = np.maximum.accumulate(wealth, axis=0)
        drawdown = np.max(1.0 - wealth / np.maximum(running_peak, 1e-12), axis=0)
        base = _softmax_standardized(mean / safe_volatility, fallback=equal)
        risk_scale = safe_volatility * np.sqrt(len(history))
        penalty = 1.0 / (1.0 + drawdown / np.maximum(risk_scale, 1e-12))
        return _normalize_positive(base * penalty, fallback=equal)
    if rule == "return_to_turnover":
        if turnover is None:
            raise ValueError("return_to_turnover requires turnover observations.")
        annual_turnover = turnover.mean(axis=0).to_numpy(dtype="float64") * 252.0
        positive_mean = np.clip(mean, 0.0, None)
        score = positive_mean / (
            safe_volatility * (1.0 + np.maximum(annual_turnover, 0.0))
        )
        return _normalize_positive(
            score,
            fallback=_normalize_positive(1.0 / safe_volatility, fallback=equal),
        )
    if rule == "rank_momentum":
        sharpe = mean / safe_volatility
        finite = np.isfinite(sharpe)
        if finite.sum() < 2:
            return equal
        floor = float(np.nanmin(sharpe[finite]))
        ranked = pd.Series(np.where(finite, sharpe, floor)).rank(
            method="average"
        ).to_numpy(dtype="float64")
        return _normalize_positive(ranked, fallback=equal)
    if rule == "positive_sharpe_squared":
        sharpe = np.clip(mean / safe_volatility, 0.0, None)
        return _normalize_positive(
            np.square(sharpe),
            fallback=_normalize_positive(1.0 / safe_volatility, fallback=equal),
        )
    if rule == "momentum_diversification":
        correlation = history.corr().abs().to_numpy(dtype="float64", copy=True)
        np.fill_diagonal(correlation, 0.0)
        average_correlation = correlation.sum(axis=1) / max(1, len(correlation) - 1)
        score = np.clip(mean / safe_volatility, 0.0, None) / (
            1.0 + average_correlation
        )
        return _normalize_positive(
            score,
            fallback=_normalize_positive(1.0 / safe_volatility, fallback=equal),
        )
    if rule == "cost_adjusted_momentum":
        if turnover is None:
            raise ValueError("cost_adjusted_momentum requires turnover observations.")
        # Zero-net sleeves have nearly equal buy/sell notional, so 13bp per
        # one-way average is the direct 3/23bp asymmetric-cost implication.
        cost_adjusted_mean = mean - turnover.mean(axis=0).to_numpy(
            dtype="float64"
        ) * 0.0013
        score = np.clip(cost_adjusted_mean, 0.0, None) / np.square(
            safe_volatility
        )
        return _normalize_positive(
            score,
            fallback=_normalize_positive(1.0 / safe_volatility, fallback=equal),
        )
    if rule == "minimum_variance_momentum":
        covariance = np.cov(values, rowvar=False, ddof=1)
        covariance = np.atleast_2d(covariance)
        diagonal = np.diag(np.diag(covariance))
        shrunk = 0.5 * covariance + 0.5 * diagonal
        penalty = float(np.trace(shrunk) / len(shrunk))
        minimum_variance = _minimum_variance_with_turnover(
            shrunk,
            previous=previous,
            penalty=penalty,
        )
        momentum = _softmax_standardized(
            mean / safe_volatility,
            fallback=equal,
        )
        return _normalize_positive(
            minimum_variance * momentum,
            fallback=equal,
        )
    raise ValueError(f"Unsupported dynamic allocation rule: {rule}")


def _minimum_variance_with_turnover(
    covariance: np.ndarray,
    *,
    previous: np.ndarray,
    penalty: float,
) -> np.ndarray:
    count = len(previous)
    equal = np.repeat(1.0 / count, count)
    if covariance.shape != (count, count) or not np.isfinite(covariance).all():
        return equal
    spectral = float(np.linalg.norm(covariance, ord=2))
    step = 1.0 / max(2.0 * (spectral + penalty), 1e-12)
    weights = previous.copy()
    for _ in range(250):
        gradient = 2.0 * covariance @ weights + 2.0 * penalty * (
            weights - previous
        )
        updated = _project_simplex(weights - step * gradient)
        if np.max(np.abs(updated - weights)) < 1e-12:
            weights = updated
            break
        weights = updated
    return _normalize_positive(weights, fallback=equal)


def _project_simplex(values: np.ndarray) -> np.ndarray:
    ordered = np.sort(values)[::-1]
    cumulative = np.cumsum(ordered) - 1.0
    indices = np.arange(1, len(values) + 1)
    valid = ordered - cumulative / indices > 0.0
    if not valid.any():
        return np.repeat(1.0 / len(values), len(values))
    rho = int(indices[valid][-1])
    threshold = cumulative[rho - 1] / rho
    return np.maximum(values - threshold, 0.0)


def _softmax_standardized(
    scores: np.ndarray,
    *,
    fallback: np.ndarray,
) -> np.ndarray:
    finite = np.isfinite(scores)
    if finite.sum() < 2:
        return fallback.copy()
    filled = scores.copy()
    filled[~finite] = np.nanmin(filled[finite])
    dispersion = float(filled.std(ddof=1))
    if dispersion <= 1e-12:
        return fallback.copy()
    standardized = (filled - filled.mean()) / dispersion
    shifted = standardized - standardized.max()
    return _normalize_positive(np.exp(shifted), fallback=fallback)


def _normalize_positive(
    values: np.ndarray,
    *,
    fallback: np.ndarray,
) -> np.ndarray:
    clean = np.where(np.isfinite(values), np.maximum(values, 0.0), 0.0)
    total = float(clean.sum())
    if total <= 1e-12:
        return fallback.copy()
    return clean / total
