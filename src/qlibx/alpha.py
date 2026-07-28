"""Deterministic signed-alpha transforms and diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    long: pd.Series
    short: pd.Series
    gross: pd.Series
    net: pd.Series
    coverage: pd.Series
    missingness: pd.Series


@dataclass(frozen=True, slots=True)
class OperationContract:
    operation_id: str
    version: str
    axis: str
    tie_behavior: str
    nan_behavior: str
    minimum_observations: int | None
    group_missing_behavior: str
    dtype: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransformResult:
    values: pd.DataFrame
    lineage: tuple[OperationContract, ...]
    neutrality_warning: str | None = None


@dataclass(frozen=True, slots=True)
class ExposureArtifact:
    analyzer_id: str
    analyzer_version: str
    input_id: str
    dataset_ids: Mapping[str, str]
    estimation_window: tuple[str, str]
    method: str
    summary: ExposureSummary
    market_exposure: pd.Series | None
    benchmark_exposure: pd.Series | None
    group_exposure: pd.DataFrame | None
    factor_exposure: pd.DataFrame | None
    intended_realized_gap: ExposureSummary | None
    coverage: pd.Series
    missingness: pd.Series
    neutrality_warning: str


OPERATION_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    "cross_sectional_rank": {
        "operation_id": "qlibx.alpha.cross_sectional_rank",
        "version": "1",
        "axis": "date_by_ticker",
        "tie_behavior": "average_percentile_rank",
        "nan_behavior": "preserve",
        "minimum_observations": 1,
        "group_missing_behavior": "not_applicable",
        "dtype": "float64",
    },
    "cross_sectional_demean": {
        "operation_id": "qlibx.alpha.cross_sectional_demean",
        "version": "1",
        "axis": "date_by_ticker",
        "tie_behavior": "not_applicable",
        "nan_behavior": "exclude_from_mean_and_preserve",
        "minimum_observations": 1,
        "group_missing_behavior": "not_applicable",
        "dtype": "float64",
    },
    "group_demean": {
        "operation_id": "qlibx.alpha.group_demean",
        "version": "1",
        "axis": "date_by_ticker_with_group",
        "tie_behavior": "not_applicable",
        "nan_behavior": "exclude_from_group_mean_and_preserve",
        "minimum_observations": 1,
        "group_missing_behavior": "missing_group_produces_missing_output",
        "dtype": "float64",
    },
    "linear_decay": {
        "operation_id": "qlibx.alpha.linear_decay",
        "version": "1",
        "axis": "time_by_ticker",
        "tie_behavior": "not_applicable",
        "nan_behavior": "full_window_required",
        "minimum_observations": None,
        "group_missing_behavior": "not_applicable",
        "dtype": "float64",
    },
    "hump": {
        "operation_id": "qlibx.alpha.hump",
        "version": "1",
        "axis": "time_by_ticker",
        "tie_behavior": "not_applicable",
        "nan_behavior": "preserve_without_fill",
        "minimum_observations": 1,
        "group_missing_behavior": "not_applicable",
        "dtype": "float64",
    },
}

NEUTRALITY_WARNING = (
    "A transform is not proof of exact market, benchmark, industry, sector, or factor neutrality."
)


def cross_sectional_rank(values: pd.DataFrame) -> pd.DataFrame:
    """Return centered percentile ranks in [-0.5, 0.5], preserving missing values."""
    return values.rank(axis=1, method="average", pct=True) - 0.5


def cross_sectional_demean(values: pd.DataFrame) -> pd.DataFrame:
    return values.sub(values.mean(axis=1), axis=0)


def cross_sectional_zscore(values: pd.DataFrame, *, minimum_count: int = 2) -> pd.DataFrame:
    count = values.count(axis=1)
    mean = values.mean(axis=1)
    scale = values.std(axis=1, ddof=0).replace(0.0, pd.NA)
    result = values.sub(mean, axis=0).div(scale, axis=0)
    return result.where(count.ge(minimum_count), pd.NA)


def winsorize(values: pd.DataFrame, *, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    if not 0 <= lower <= upper <= 1:
        raise ValueError("winsorize quantiles must satisfy 0 <= lower <= upper <= 1")
    floors = values.quantile(lower, axis=1)
    ceilings = values.quantile(upper, axis=1)
    return values.clip(lower=floors, upper=ceilings, axis=0)


def group_demean(values: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    """Demean each date within explicit ticker groups; missing groups stay missing."""
    values, groups = values.align(groups, join="left")
    result = pd.DataFrame(index=values.index, columns=values.columns, dtype="float64")
    for date in values.index:
        row = values.loc[date]
        labels = groups.loc[date]
        valid = row.notna() & labels.notna()
        result.loc[date, valid] = row[valid] - row[valid].groupby(labels[valid]).transform("mean")
    return result


def linear_decay(values: pd.DataFrame, *, window: int) -> pd.DataFrame:
    if window < 1:
        raise ValueError("window must be positive")
    weights = pd.Series(range(1, window + 1), dtype="float64")
    denominator = float(weights.sum())
    return values.rolling(window, min_periods=window).apply(
        lambda series: float(series.reset_index(drop=True).mul(weights).sum()) / denominator,
        raw=False,
    )


def hump(values: pd.DataFrame, *, maximum_change: float) -> pd.DataFrame:
    """Limit each ticker's step change without filling missing observations."""
    if maximum_change < 0:
        raise ValueError("maximum_change must be non-negative")
    result = values.copy().astype("float64")
    for offset in range(1, len(result.index)):
        previous = result.iloc[offset - 1]
        current = result.iloc[offset]
        delta = current.sub(previous).clip(-maximum_change, maximum_change)
        result.iloc[offset] = previous.add(delta).where(current.notna(), pd.NA)
    return result


def top_bottom(values: pd.DataFrame, *, count: int) -> pd.DataFrame:
    if count < 1:
        raise ValueError("count must be positive")
    ranks_ascending = values.rank(axis=1, method="first", ascending=True)
    ranks_descending = values.rank(axis=1, method="first", ascending=False)
    selected = pd.DataFrame(0.0, index=values.index, columns=values.columns)
    selected = selected.mask(ranks_descending.le(count), 1.0)
    selected = selected.mask(ranks_ascending.le(count), -1.0)
    return selected.where(values.notna(), pd.NA)


def rescale_budget(
    weights: pd.DataFrame,
    *,
    mode: Literal["fixed", "flexible"] = "fixed",
    long_budget: float = 1.0,
    short_budget: float = 1.0,
) -> pd.DataFrame:
    """Apply explicit side budgets; flexible mode never scales a side upward."""
    if long_budget < 0 or short_budget < 0:
        raise ValueError("side budgets must be non-negative")
    if mode not in {"fixed", "flexible"}:
        raise ValueError("mode must be fixed or flexible")
    positive = weights.clip(lower=0.0)
    negative = weights.clip(upper=0.0)
    long_sum = positive.sum(axis=1)
    short_sum = -negative.sum(axis=1)
    long_scale = long_budget / long_sum.replace(0.0, pd.NA)
    short_scale = short_budget / short_sum.replace(0.0, pd.NA)
    if mode == "flexible":
        long_scale = long_scale.clip(upper=1.0)
        short_scale = short_scale.clip(upper=1.0)
    result = positive.mul(long_scale.fillna(0.0), axis=0)
    result += negative.mul(short_scale.fillna(0.0), axis=0)
    return result.where(weights.notna(), pd.NA)


def exposure_summary(weights: pd.DataFrame) -> ExposureSummary:
    long = weights.clip(lower=0.0).sum(axis=1)
    short = weights.clip(upper=0.0).sum(axis=1)
    gross = long - short
    net = long + short
    coverage = weights.notna().sum(axis=1)
    missingness = weights.isna().mean(axis=1)
    return ExposureSummary(long, short, gross, net, coverage, missingness)


def operation_contract(name: str, **parameters: Any) -> OperationContract:
    """Return the versioned semantics that become transform lineage."""
    if name not in OPERATION_CONTRACTS:
        raise ValueError(f"unknown alpha operation: {name}")
    raw = OPERATION_CONTRACTS[name]
    minimum = raw["minimum_observations"]
    if name == "linear_decay" and "window" in parameters:
        minimum = int(parameters["window"])
    return OperationContract(
        operation_id=str(raw["operation_id"]),
        version=str(raw["version"]),
        axis=str(raw["axis"]),
        tie_behavior=str(raw["tie_behavior"]),
        nan_behavior=str(raw["nan_behavior"]),
        minimum_observations=None if minimum is None else int(minimum),
        group_missing_behavior=str(raw["group_missing_behavior"]),
        dtype=str(raw["dtype"]),
        parameters=dict(parameters),
    )


def apply_transform(
    name: str,
    values: pd.DataFrame,
    *,
    groups: pd.DataFrame | None = None,
    **parameters: Any,
) -> TransformResult:
    """Apply one deterministic built-in and return its explicit lineage."""
    if name == "cross_sectional_rank":
        transformed = cross_sectional_rank(values)
    elif name == "cross_sectional_demean":
        transformed = cross_sectional_demean(values)
    elif name == "group_demean":
        if groups is None:
            raise ValueError("group_demean requires explicit groups")
        transformed = group_demean(values, groups)
    elif name == "linear_decay":
        transformed = linear_decay(values, window=int(parameters["window"]))
    elif name == "hump":
        transformed = hump(values, maximum_change=float(parameters["maximum_change"]))
    else:
        raise ValueError(f"unknown alpha operation: {name}")
    warning = NEUTRALITY_WARNING if name in {"cross_sectional_demean", "group_demean"} else None
    return TransformResult(
        transformed,
        (operation_contract(name, **parameters),),
        warning,
    )


def analyze_exposure(
    weights: pd.DataFrame,
    *,
    input_id: str,
    dataset_ids: Mapping[str, str],
    method: str,
    market_beta: pd.DataFrame | None = None,
    benchmark_beta: pd.DataFrame | None = None,
    groups: pd.DataFrame | None = None,
    factors: Mapping[str, pd.DataFrame] | None = None,
    realized_holdings: pd.DataFrame | None = None,
    analyzer_id: str = "qlibx.alpha.exposure",
    analyzer_version: str = "1",
) -> ExposureArtifact:
    """Measure declared exposures without claiming exact neutrality."""
    if weights.empty:
        raise ValueError("exposure analysis requires at least one row")
    summary = exposure_summary(weights)
    market = _weighted_exposure(weights, market_beta, "market_beta")
    benchmark = _weighted_exposure(weights, benchmark_beta, "benchmark_beta")
    group = _group_exposure(weights, groups) if groups is not None else None
    factor = None
    if factors:
        columns = {
            name: _weighted_exposure(weights, values, f"factor {name}")
            for name, values in factors.items()
        }
        factor = pd.DataFrame(columns, index=weights.index)
    gap = None
    if realized_holdings is not None:
        intended, realized = weights.align(realized_holdings, join="outer")
        gap = exposure_summary(realized.sub(intended))
    return ExposureArtifact(
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        input_id=input_id,
        dataset_ids=dict(dataset_ids),
        estimation_window=(str(weights.index.min()), str(weights.index.max())),
        method=method,
        summary=summary,
        market_exposure=market,
        benchmark_exposure=benchmark,
        group_exposure=group,
        factor_exposure=factor,
        intended_realized_gap=gap,
        coverage=summary.coverage,
        missingness=summary.missingness,
        neutrality_warning=NEUTRALITY_WARNING,
    )


def _weighted_exposure(
    weights: pd.DataFrame,
    exposures: pd.DataFrame | None,
    label: str,
) -> pd.Series | None:
    if exposures is None:
        return None
    aligned_weights, aligned_exposures = weights.align(exposures, join="left")
    if not aligned_exposures.index.equals(weights.index):
        raise ValueError(f"{label} index is incompatible with weights")
    return aligned_weights.mul(aligned_exposures).sum(axis=1, min_count=1)


def _group_exposure(weights: pd.DataFrame, groups: pd.DataFrame) -> pd.DataFrame:
    aligned_weights, aligned_groups = weights.align(groups, join="left")
    labels = sorted({str(value) for value in aligned_groups.to_numpy().ravel() if pd.notna(value)})
    output = pd.DataFrame(0.0, index=aligned_weights.index, columns=labels)
    for date in aligned_weights.index:
        row = aligned_weights.loc[date]
        row_groups = aligned_groups.loc[date]
        for label in labels:
            members = row_groups.astype("string").eq(label)
            output.loc[date, label] = row.where(members).sum(min_count=1)
    return output
