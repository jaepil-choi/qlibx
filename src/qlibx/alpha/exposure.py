"""Exposure measurement with explicit requested metrics and requirement gaps."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from qlibx.errors import requirement_gap
from qlibx.requirements import (
    CapabilityPlan,
    CapabilityRequirement,
    CapabilityRequirements,
    CapabilityResolution,
    DerivationAlternative,
    RequirementEvidence,
    UnavailableOutput,
    evaluate_requirements,
    make_plan,
)

from .contracts import NEUTRALITY_WARNING

ExposureMetric = Literal[
    "summary",
    "market_exposure",
    "benchmark_exposure",
    "group_exposure",
    "factor_exposure",
    "intended_realized_gap",
]
EXPOSURE_METRICS: tuple[ExposureMetric, ...] = (
    "summary",
    "market_exposure",
    "benchmark_exposure",
    "group_exposure",
    "factor_exposure",
    "intended_realized_gap",
)
_METRIC_REQUIREMENT = {
    "summary": "weights",
    "market_exposure": "market_beta",
    "benchmark_exposure": "benchmark_beta",
    "group_exposure": "group_label",
    "factor_exposure": "factor_exposures",
    "intended_realized_gap": "realized_holdings",
}
_REQUIREMENT_METRIC = {value: key for key, value in _METRIC_REQUIREMENT.items()}


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
    requested_metrics: tuple[ExposureMetric, ...]
    status: Literal["complete", "incomplete"]
    requirement_resolution: CapabilityResolution
    unavailable_outputs: tuple[UnavailableOutput, ...]
    summary: ExposureSummary
    market_exposure: pd.Series | None
    benchmark_exposure: pd.Series | None
    group_exposure: pd.DataFrame | None
    factor_exposure: pd.DataFrame | None
    intended_realized_gap: ExposureSummary | None
    coverage: pd.Series
    missingness: pd.Series
    neutrality_warning: str


def _requirement(
    requirement_id: str,
    *,
    role: str,
    meaning: str,
    axis: str,
    unit: str,
    purpose: str,
    mandatory: bool,
    unavailable_effect: str,
) -> CapabilityRequirement:
    return CapabilityRequirement(
        requirement_id=requirement_id,
        role=role,
        meaning=meaning,
        axis=axis,
        unit=unit,
        currency="project_declared_or_not_applicable",
        purpose=purpose,
        satisfaction_rule=f"The caller supplies explicit {role} input.",
        availability="Input is bounded by the artifact or decision-time availability contract.",
        mandatory=mandatory,
        unavailable_effect=unavailable_effect,
        alternatives=(
            DerivationAlternative(
                alternative_id=f"explicit_{requirement_id}",
                description=f"Use explicit {meaning.lower()}",
                required_inputs=(role,),
                derivation="direct",
            ),
        ),
        next_commands=(
            "qlibx data catalog --root <project>",
            "qlibx alpha exposure-plan --metric <metric> --provided-input <role>",
        ),
    )


def exposure_requirements() -> CapabilityRequirements:
    return CapabilityRequirements(
        capability_id="qlibx.alpha.exposure",
        capability_version="2",
        summary="Measure only explicitly requested signed-weight exposure outputs.",
        requirements=(
            _requirement(
                "weights",
                role="weights",
                meaning="Signed date-by-ticker weight matrix.",
                axis="date_by_ticker",
                unit="portfolio_weight",
                purpose="Calculate long, short, gross, net, coverage, and missingness.",
                mandatory=True,
                unavailable_effect="No exposure output can be calculated.",
            ),
            _requirement(
                "market_beta",
                role="market_beta",
                meaning="Point-in-time ticker market-beta matrix.",
                axis="date_by_ticker",
                unit="beta",
                purpose="Calculate requested market exposure.",
                mandatory=False,
                unavailable_effect="Market exposure is unavailable.",
            ),
            _requirement(
                "benchmark_beta",
                role="benchmark_beta",
                meaning="Point-in-time ticker benchmark-beta matrix.",
                axis="date_by_ticker",
                unit="beta",
                purpose="Calculate requested benchmark exposure.",
                mandatory=False,
                unavailable_effect="Benchmark exposure is unavailable.",
            ),
            _requirement(
                "group_label",
                role="group_label",
                meaning="Point-in-time ticker group-label matrix.",
                axis="date_by_ticker",
                unit="category",
                purpose="Calculate requested group exposure.",
                mandatory=False,
                unavailable_effect="Group exposure is unavailable.",
            ),
            _requirement(
                "factor_exposures",
                role="factor_exposures",
                meaning="Named point-in-time ticker factor-exposure matrices.",
                axis="factor_by_date_by_ticker",
                unit="factor_loading",
                purpose="Calculate requested user-supplied factor exposure.",
                mandatory=False,
                unavailable_effect="Factor exposure is unavailable.",
            ),
            _requirement(
                "realized_holdings",
                role="realized_holdings",
                meaning="Realized date-by-ticker holding matrix.",
                axis="date_by_ticker",
                unit="portfolio_weight",
                purpose="Calculate the requested intended-versus-realized exposure gap.",
                mandatory=False,
                unavailable_effect="The intended-realized exposure gap is unavailable.",
            ),
        ),
    )


def _validated_metrics(metrics: Iterable[str]) -> tuple[ExposureMetric, ...]:
    selected = tuple(dict.fromkeys(str(item) for item in metrics))
    unknown = sorted(set(selected) - set(EXPOSURE_METRICS))
    if unknown:
        raise ValueError(f"unknown exposure metrics: {unknown}")
    if not selected:
        raise ValueError("requested_metrics must contain at least one exposure metric")
    return selected  # type: ignore[return-value]


def plan_exposure(
    *,
    requested_metrics: Iterable[str],
    available_inputs: Iterable[str] = (),
) -> CapabilityPlan:
    selected = _validated_metrics(requested_metrics)
    declaration = exposure_requirements()
    available = set(available_inputs)
    evidence: list[RequirementEvidence] = []
    for requirement in declaration.requirements:
        supplied = requirement.role in available
        evidence.append(
            RequirementEvidence(
                requirement_id=requirement.requirement_id,
                alternative_id=f"explicit_{requirement.requirement_id}",
                satisfied=supplied,
                reason=(
                    f"Explicit {requirement.role} input is available."
                    if supplied
                    else f"Explicit {requirement.role} input was not provided."
                ),
                source="runtime_arguments",
                details={"available_inputs": sorted(available)},
            )
        )
    requested_optional = tuple(_METRIC_REQUIREMENT[item] for item in selected if item != "summary")
    resolution = evaluate_requirements(
        declaration,
        tuple(evidence),
        requested_optional=requested_optional,
    )
    return make_plan(
        declaration,
        resolution,
        parameters={
            "requested_metrics": list(selected),
            "available_inputs": sorted(available),
        },
    )


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
    requested_metrics: Iterable[str],
    market_beta: pd.DataFrame | None = None,
    benchmark_beta: pd.DataFrame | None = None,
    groups: pd.DataFrame | None = None,
    factors: Mapping[str, pd.DataFrame] | None = None,
    realized_holdings: pd.DataFrame | None = None,
    allow_incomplete: bool = False,
    analyzer_id: str = "qlibx.alpha.exposure",
    analyzer_version: str = "2",
) -> ExposureArtifact:
    """Measure requested exposures and never confuse absent input with an unrequested output."""
    if weights.empty:
        raise ValueError("exposure analysis requires at least one row")
    selected = _validated_metrics(requested_metrics)
    available = {"weights"}
    if market_beta is not None:
        available.add("market_beta")
    if benchmark_beta is not None:
        available.add("benchmark_beta")
    if groups is not None:
        available.add("group_label")
    if factors:
        available.add("factor_exposures")
    if realized_holdings is not None:
        available.add("realized_holdings")
    plan = plan_exposure(requested_metrics=selected, available_inputs=available)
    if not plan.ready and not allow_incomplete:
        raise requirement_gap(plan.resolution.to_dict())
    unavailable = tuple(
        UnavailableOutput(
            output_id=_REQUIREMENT_METRIC[item.requirement_id],
            requirement_ids=(item.requirement_id,),
            reason=item.reason,
        )
        for item in plan.resolution.results
        if item.status == "unsatisfied" and item.requirement_id in _REQUIREMENT_METRIC
    )
    summary = exposure_summary(weights)
    market = (
        _weighted_exposure(weights, market_beta, "market_beta")
        if "market_exposure" in selected and market_beta is not None
        else None
    )
    benchmark = (
        _weighted_exposure(weights, benchmark_beta, "benchmark_beta")
        if "benchmark_exposure" in selected and benchmark_beta is not None
        else None
    )
    group = (
        _group_exposure(weights, groups)
        if "group_exposure" in selected and groups is not None
        else None
    )
    factor = None
    if "factor_exposure" in selected and factors:
        columns = {
            name: _weighted_exposure(weights, values, f"factor {name}")
            for name, values in factors.items()
        }
        factor = pd.DataFrame(columns, index=weights.index)
    gap = None
    if "intended_realized_gap" in selected and realized_holdings is not None:
        intended, realized = weights.align(realized_holdings, join="outer")
        gap = exposure_summary(realized.sub(intended))
    return ExposureArtifact(
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        input_id=input_id,
        dataset_ids=dict(dataset_ids),
        estimation_window=(str(weights.index.min()), str(weights.index.max())),
        method=method,
        requested_metrics=selected,
        status="complete" if plan.ready else "incomplete",
        requirement_resolution=plan.resolution,
        unavailable_outputs=unavailable,
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
    exposures: pd.DataFrame,
    label: str,
) -> pd.Series:
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
    "EXPOSURE_METRICS",
    "ExposureArtifact",
    "ExposureMetric",
    "ExposureSummary",
    "analyze_exposure",
    "exposure_requirements",
    "exposure_summary",
    "plan_exposure",
]
