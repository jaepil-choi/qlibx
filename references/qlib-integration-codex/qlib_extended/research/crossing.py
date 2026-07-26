from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd


TRADING_DAYS = 252


@dataclass(frozen=True)
class CrossingDiagnostics:
    daily: pd.DataFrame
    summary: dict[str, float | int | str]


def validate_weight_matrix(weight: pd.DataFrame, *, name: str) -> pd.DataFrame:
    if not isinstance(weight, pd.DataFrame):
        raise TypeError(f"{name} weight must be a pandas DataFrame.")
    if not isinstance(weight.index, pd.DatetimeIndex):
        raise TypeError(f"{name} weight index must be a DatetimeIndex.")
    if weight.index.has_duplicates:
        raise ValueError(f"{name} weight index contains duplicate dates.")
    if weight.columns.has_duplicates:
        raise ValueError(f"{name} weight columns contain duplicate tickers.")
    if not weight.index.is_monotonic_increasing:
        raise ValueError(f"{name} weight dates must be sorted.")
    if weight.empty or weight.shape[1] == 0:
        raise ValueError(f"{name} weight matrix must not be empty.")
    numeric = weight.astype("float64")
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError(f"{name} weight matrix contains non-finite values.")
    return numeric


def align_weight_matrices(
    weights: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    if len(weights) < 2:
        raise ValueError("At least two weight matrices are required.")
    validated = {
        name: validate_weight_matrix(weight, name=name)
        for name, weight in weights.items()
    }
    first_name = next(iter(validated))
    first = validated[first_name]
    for name, weight in validated.items():
        if not first.index.equals(weight.index):
            raise ValueError(
                f"{name} and {first_name} must have the exact same date index."
            )
        if not first.columns.equals(weight.columns):
            raise ValueError(
                f"{name} and {first_name} must have the exact same ticker columns."
            )
    return validated


def normalize_allocations(
    names: list[str],
    allocations: Mapping[str, float] | None,
) -> dict[str, float]:
    if allocations is None:
        return {name: 1.0 / len(names) for name in names}
    missing = sorted(set(names) - set(allocations))
    extra = sorted(set(allocations) - set(names))
    if missing or extra:
        raise ValueError(
            f"Allocation names disagree with weight names: missing={missing}, extra={extra}"
        )
    values = {name: float(allocations[name]) for name in names}
    if any(not np.isfinite(value) or value < 0.0 for value in values.values()):
        raise ValueError("Allocations must be finite and non-negative.")
    total = sum(values.values())
    if total <= 0.0:
        raise ValueError("Allocations must have a positive sum.")
    return {name: value / total for name, value in values.items()}


def compute_crossing_diagnostics(
    weights: Mapping[str, pd.DataFrame],
    *,
    allocations: Mapping[str, float] | None = None,
    realized_return: pd.DataFrame | None = None,
    buy_cost: float = 0.0003,
    sell_cost: float = 0.0023,
    label: str = "ensemble",
) -> CrossingDiagnostics:
    aligned = align_weight_matrices(weights)
    names = list(aligned)
    normalized = normalize_allocations(names, allocations)
    if buy_cost < 0.0 or sell_cost < 0.0:
        raise ValueError("Trade costs must be non-negative.")

    scaled = {name: aligned[name] * normalized[name] for name in names}
    combined = sum(scaled.values())
    naive_position_gross = sum(weight.abs() for weight in scaled.values()).sum(axis=1)
    combined_position_gross = combined.abs().sum(axis=1)
    position_netting_saving = naive_position_gross - combined_position_gross

    changes = {name: weight.diff().fillna(weight) for name, weight in scaled.items()}
    combined_change = sum(changes.values())
    naive_buy = sum(change.clip(lower=0.0) for change in changes.values()).sum(axis=1)
    naive_sell = -sum(change.clip(upper=0.0) for change in changes.values()).sum(axis=1)
    combined_buy = combined_change.clip(lower=0.0).sum(axis=1)
    combined_sell = -combined_change.clip(upper=0.0).sum(axis=1)
    naive_trade_gross = naive_buy + naive_sell
    combined_trade_gross = combined_buy + combined_sell
    crossing_saving_gross = naive_trade_gross - combined_trade_gross

    naive_cost = naive_buy * buy_cost + naive_sell * sell_cost
    combined_cost = combined_buy * buy_cost + combined_sell * sell_cost
    daily = pd.DataFrame(
        {
            "naive_position_gross": naive_position_gross,
            "combined_position_gross": combined_position_gross,
            "position_netting_saving_gross": position_netting_saving,
            "position_netting_rate": safe_ratio(position_netting_saving, naive_position_gross),
            "naive_buy": naive_buy,
            "naive_sell": naive_sell,
            "combined_buy": combined_buy,
            "combined_sell": combined_sell,
            "naive_trade_gross": naive_trade_gross,
            "combined_trade_gross": combined_trade_gross,
            "crossing_saving_gross": crossing_saving_gross,
            "internal_crossing_notional": crossing_saving_gross / 2.0,
            "trade_crossing_rate": safe_ratio(crossing_saving_gross, naive_trade_gross),
            "naive_trade_cost": naive_cost,
            "combined_trade_cost": combined_cost,
            "crossing_cost_saving": naive_cost - combined_cost,
        },
        index=combined.index,
    )
    if realized_return is not None:
        realized = validate_realized_return(realized_return, template=combined)
        daily["combined_gross_return"] = (combined * realized).sum(axis=1)
        daily["combined_net_return"] = (
            daily["combined_gross_return"] - daily["combined_trade_cost"]
        )
    daily.index.name = "date"
    summary = summarize_crossing(daily, label=label, member_count=len(names))
    return CrossingDiagnostics(daily=daily, summary=summary)


def compute_pairwise_diagnostics(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_name: str,
    right_name: str,
    left_allocation: float = 0.5,
    right_allocation: float = 0.5,
    realized_return: pd.DataFrame | None = None,
    buy_cost: float = 0.0003,
    sell_cost: float = 0.0023,
) -> CrossingDiagnostics:
    aligned = align_weight_matrices({left_name: left, right_name: right})
    result = compute_crossing_diagnostics(
        aligned,
        allocations={left_name: left_allocation, right_name: right_allocation},
        buy_cost=buy_cost,
        sell_cost=sell_cost,
        label=f"{left_name}__{right_name}",
    )
    left_weight = aligned[left_name]
    right_weight = aligned[right_name]
    active = left_weight.ne(0.0) | right_weight.ne(0.0)
    left_active = left_weight.where(active)
    right_active = right_weight.where(active)
    cross_sectional_corr = left_active.corrwith(right_active, axis=1)
    dot = (left_weight * right_weight).sum(axis=1)
    denominator = (
        left_weight.pow(2).sum(axis=1).pow(0.5)
        * right_weight.pow(2).sum(axis=1).pow(0.5)
    )
    cross_sectional_cosine = safe_ratio(dot, denominator)
    opposite = np.sign(left_weight) * np.sign(right_weight) < 0.0
    same = np.sign(left_weight) * np.sign(right_weight) > 0.0
    overlap = np.minimum(left_weight.abs(), right_weight.abs())

    daily = result.daily.copy()
    daily["cross_sectional_weight_corr"] = cross_sectional_corr
    daily["cross_sectional_weight_cosine"] = cross_sectional_cosine
    daily["opposite_position_overlap"] = overlap.where(opposite, 0.0).sum(axis=1)
    daily["same_direction_position_overlap"] = overlap.where(same, 0.0).sum(axis=1)

    summary = dict(result.summary)
    summary.update(
        {
            "left": left_name,
            "right": right_name,
            "mean_cross_sectional_weight_corr": float(cross_sectional_corr.mean()),
            "mean_cross_sectional_weight_cosine": float(cross_sectional_cosine.mean()),
            "mean_opposite_position_overlap": float(
                daily["opposite_position_overlap"].mean()
            ),
            "mean_same_direction_position_overlap": float(
                daily["same_direction_position_overlap"].mean()
            ),
        }
    )
    if realized_return is not None:
        realized = validate_realized_return(realized_return, template=left_weight)
        left_return = (left_weight * realized).sum(axis=1)
        right_return = (right_weight * realized).sum(axis=1)
        daily["left_gross_return"] = left_return
        daily["right_gross_return"] = right_return
        summary["return_correlation"] = float(left_return.corr(right_return))
    return CrossingDiagnostics(daily=daily, summary=summary)


def validate_realized_return(
    realized_return: pd.DataFrame,
    *,
    template: pd.DataFrame,
) -> pd.DataFrame:
    realized = validate_weight_matrix(realized_return.fillna(0.0), name="realized_return")
    if not template.index.equals(realized.index):
        raise ValueError("Realized returns and weights must have the exact same date index.")
    if not template.columns.equals(realized.columns):
        raise ValueError(
            "Realized returns and weights must have the exact same ticker columns."
        )
    return realized


def summarize_crossing(
    daily: pd.DataFrame,
    *,
    label: str,
    member_count: int,
) -> dict[str, float | int | str]:
    years = len(daily) / TRADING_DAYS
    naive_trade = float(daily["naive_trade_gross"].sum())
    combined_trade = float(daily["combined_trade_gross"].sum())
    naive_cost = float(daily["naive_trade_cost"].sum())
    combined_cost = float(daily["combined_trade_cost"].sum())
    summary: dict[str, float | int | str] = {
        "label": label,
        "member_count": member_count,
        "n_days": len(daily),
        "mean_position_netting_rate": float(daily["position_netting_rate"].mean()),
        "mean_trade_crossing_rate": float(daily["trade_crossing_rate"].mean()),
        "aggregate_trade_crossing_rate": (
            1.0 - combined_trade / naive_trade if naive_trade > 0.0 else 0.0
        ),
        "annualized_naive_one_way_turnover": (
            naive_trade / 2.0 / years if years > 0.0 else 0.0
        ),
        "annualized_combined_one_way_turnover": (
            combined_trade / 2.0 / years if years > 0.0 else 0.0
        ),
        "annualized_naive_cost_bp": (
            naive_cost * 10_000.0 / years if years > 0.0 else 0.0
        ),
        "annualized_combined_cost_bp": (
            combined_cost * 10_000.0 / years if years > 0.0 else 0.0
        ),
        "annualized_crossing_cost_saving_bp": (
            (naive_cost - combined_cost) * 10_000.0 / years
            if years > 0.0
            else 0.0
        ),
    }
    for kind in ("gross", "net"):
        column = f"combined_{kind}_return"
        if column in daily:
            annual_return, annual_volatility, sharpe = annualized_returns(
                daily[column]
            )
            summary[f"annualized_{kind}_return"] = annual_return
            summary[f"annualized_{kind}_volatility"] = annual_volatility
            summary[f"{kind}_sharpe"] = sharpe
    return summary


def annualized_returns(returns: pd.Series) -> tuple[float, float, float]:
    annual_return = float(returns.mean() * TRADING_DAYS)
    annual_volatility = float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe = annual_return / annual_volatility if annual_volatility > 0.0 else 0.0
    return annual_return, annual_volatility, sharpe


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator.abs().gt(1e-15))).fillna(0.0)
