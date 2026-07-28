"""Semantic, empirical, and incremental alpha comparison."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True, slots=True)
class AlphaDescriptor:
    alpha_id: str
    mechanism: str
    inputs: tuple[str, ...]
    observation_clock: str
    horizon: str
    operations: tuple[str, ...]
    neutralization: str | None = None


@dataclass(frozen=True, slots=True)
class OrthogonalityResult:
    candidate_id: str
    reference_id: str
    semantic_overlap: Mapping[str, bool]
    classification: str
    signal_correlation: float | None
    holding_correlation: float | None
    residual_ratio: float | None
    observations: int
    missing_comparisons: tuple[str, ...]
    reference_pool: tuple[str, ...] = ()
    evaluation_segment: Mapping[str, str] = field(default_factory=dict)
    empirical_metrics: Mapping[str, float | None] = field(default_factory=dict)
    incremental_metrics: Mapping[str, float | None] = field(default_factory=dict)
    thresholds: Mapping[str, float] = field(default_factory=dict)
    threshold_outcomes: Mapping[str, bool | None] = field(default_factory=dict)


def compare_alpha(
    candidate: AlphaDescriptor,
    reference: AlphaDescriptor,
    *,
    candidate_signal: pd.DataFrame | None = None,
    reference_signal: pd.DataFrame | None = None,
    candidate_holding: pd.DataFrame | None = None,
    reference_holding: pd.DataFrame | None = None,
    empirical_pairs: Mapping[str, tuple[pd.DataFrame | None, pd.DataFrame | None]] | None = None,
    incremental_metrics: Mapping[str, float | None] | None = None,
    reference_pool: tuple[str, ...] = (),
    evaluation_segment: Mapping[str, str] | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> OrthogonalityResult:
    semantic = {
        "mechanism": candidate.mechanism == reference.mechanism,
        "inputs": bool(set(candidate.inputs) & set(reference.inputs)),
        "clock": candidate.observation_clock == reference.observation_clock,
        "horizon": candidate.horizon == reference.horizon,
        "operations": bool(set(candidate.operations) & set(reference.operations)),
        "neutralization": candidate.neutralization == reference.neutralization,
    }
    core_overlap = all(semantic[name] for name in ("mechanism", "inputs", "clock"))
    classification = "family_variation" if core_overlap else "distinct_hypothesis"
    missing: list[str] = []
    signal_correlation, observations = _matrix_correlation(candidate_signal, reference_signal)
    if signal_correlation is None:
        missing.append("signal")
    holding_correlation, _ = _matrix_correlation(candidate_holding, reference_holding)
    if holding_correlation is None:
        missing.append("holding")
    residual_ratio = _residual_ratio(candidate_signal, reference_signal)
    if residual_ratio is None:
        missing.append("incremental_residual")
    empirical: dict[str, float | None] = {
        "signal_correlation": signal_correlation,
        "holding_correlation": holding_correlation,
    }
    for name, pair in (empirical_pairs or {}).items():
        value, _ = _matrix_correlation(*pair)
        empirical[f"{name}_correlation"] = value
        if value is None:
            missing.append(name)
    incremental = {"residual_ratio": residual_ratio, **dict(incremental_metrics or {})}
    declared_thresholds = dict(thresholds or {})
    all_metrics: dict[str, float | None] = {**empirical, **incremental}
    outcomes = {
        name: None if all_metrics.get(name) is None else bool(all_metrics[name] >= threshold)
        for name, threshold in declared_thresholds.items()
    }
    return OrthogonalityResult(
        candidate.alpha_id,
        reference.alpha_id,
        semantic,
        classification,
        signal_correlation,
        holding_correlation,
        residual_ratio,
        observations,
        tuple(missing),
        reference_pool or (reference.alpha_id,),
        dict(evaluation_segment or {}),
        empirical,
        incremental,
        declared_thresholds,
        outcomes,
    )


def _matrix_correlation(
    left: pd.DataFrame | None, right: pd.DataFrame | None
) -> tuple[float | None, int]:
    if left is None or right is None:
        return None, 0
    left, right = left.align(right, join="inner")
    paired = pd.concat(
        [left.stack().rename("left"), right.stack().rename("right")], axis=1, join="inner"
    ).dropna()
    if len(paired) < 2 or paired["left"].std() == 0 or paired["right"].std() == 0:
        return None, len(paired)
    return float(paired.corr().iloc[0, 1]), len(paired)


def _residual_ratio(left: pd.DataFrame | None, right: pd.DataFrame | None) -> float | None:
    if left is None or right is None:
        return None
    left, right = left.align(right, join="inner")
    paired = pd.concat(
        [left.stack().rename("left"), right.stack().rename("right")], axis=1, join="inner"
    ).dropna()
    if len(paired) < 2:
        return None
    denominator = float((paired["right"] ** 2).sum())
    total = float((paired["left"] ** 2).sum())
    if denominator == 0 or total == 0:
        return None
    coefficient = float((paired["left"] * paired["right"]).sum()) / denominator
    residual = paired["left"] - coefficient * paired["right"]
    return float((residual**2).sum()) / total
