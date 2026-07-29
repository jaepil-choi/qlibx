"""Exposure measurement over signed weights.

Kept separate from the operation registry: exposure analysis consumes weights and
optional market/benchmark/group/factor data, and is the surface where a missing
required dataset must become visible rather than a silently absent field.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from .contracts import NEUTRALITY_WARNING


@dataclass(frozen=True, slots=True)
class ExposureSummary:
    long: pd.Series
    short: pd.Series
    gross: pd.Series
    net: pd.Series
    coverage: pd.Series
    missingness: pd.Series


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


def exposure_summary(weights: pd.DataFrame) -> ExposureSummary:
    long = weights.clip(lower=0.0).sum(axis=1)
    short = weights.clip(upper=0.0).sum(axis=1)
    gross = long - short
    net = long + short
    coverage = weights.notna().sum(axis=1)
    missingness = weights.isna().mean(axis=1)
    return ExposureSummary(long, short, gross, net, coverage, missingness)


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

__all__ = [
    "ExposureArtifact",
    "ExposureSummary",
    "analyze_exposure",
    "exposure_summary",
]
