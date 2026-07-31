"""Verified stored signed-alpha ensemble and ticker-level netting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite

import pandas as pd

from qlibx.alpha import ExposureSummary, exposure_summary
from qlibx.errors import QlibxError
from qlibx.research import ResearchCatalog


@dataclass(frozen=True, slots=True)
class EnsembleResult:
    combined: pd.DataFrame
    contributions: Mapping[str, pd.DataFrame]
    coefficients: Mapping[str, float]
    exposure: ExposureSummary
    missing_by_member: Mapping[str, int]
    member_run_ids: tuple[str, ...] = ()
    effective_weights: Mapping[str, float] = field(default_factory=dict)
    netting: pd.DataFrame = field(default_factory=pd.DataFrame)
    member_similarity: pd.DataFrame = field(default_factory=pd.DataFrame)
    marginal_contribution: Mapping[str, float] = field(default_factory=dict)
    parent_lineage: tuple[str, ...] = ()


def combine_signed_weights(
    members: Mapping[str, pd.DataFrame],
    *,
    coefficients: Mapping[str, float] | None = None,
) -> EnsembleResult:
    """Align and sum weights without restoring member gross or cross-ticker netting."""
    if not members:
        raise QlibxError(
            "PORTFOLIO",
            "ensemble requires at least one member",
            expected="An ensemble combines at least one stored alpha record.",
        )
    selected = {name: float(value) for name, value in (coefficients or {}).items()}
    if not selected:
        selected = {name: 1.0 for name in members}
    if set(selected) != set(members):
        raise QlibxError(
            "PORTFOLIO",
            "ensemble coefficients must exactly match member names",
            expected="Every member has a coefficient and every coefficient names a member.",
            context={
                "members_without_coefficient": sorted(set(members) - set(selected)),
                "coefficients_without_member": sorted(set(selected) - set(members)),
            },
        )
    if not all(isfinite(value) for value in selected.values()):
        raise QlibxError(
            "PORTFOLIO",
            "ensemble coefficients must be finite",
            expected="Every coefficient is a finite number.",
            context={
                "non_finite": sorted(
                    name for name, value in selected.items() if not isfinite(value)
                )
            },
        )
    index_name = _shared_axis_name(members, axis="index")
    columns_name = _shared_axis_name(members, axis="columns")
    member_indexes = [frame.index for frame in members.values()]
    index_dtypes = {str(index.dtype) for index in member_indexes}
    index_dtype = member_indexes[0].dtype if len(index_dtypes) == 1 else None
    index = pd.DatetimeIndex(
        sorted(set().union(*(frame.index for frame in members.values()))),
        dtype=index_dtype,
        name=index_name,
    )
    columns = pd.Index(
        sorted(set().union(*(frame.columns for frame in members.values()))),
        name=columns_name,
    )
    contributions: dict[str, pd.DataFrame] = {}
    missing: dict[str, int] = {}
    observed = pd.DataFrame(False, index=index, columns=columns)
    combined = pd.DataFrame(0.0, index=index, columns=columns)
    gross_member_intent = pd.DataFrame(0.0, index=index, columns=columns)
    for name, frame in members.items():
        aligned = frame.reindex(index=index, columns=columns)
        missing[name] = int(aligned.isna().sum().sum())
        contribution = aligned.mul(selected[name])
        contributions[name] = contribution
        observed |= aligned.notna()
        combined = combined.add(contribution.fillna(0.0))
        gross_member_intent = gross_member_intent.add(contribution.abs().fillna(0.0))
    combined = combined.where(observed, pd.NA)
    netting = gross_member_intent.sub(combined.abs().fillna(0.0)).where(observed, pd.NA)
    contribution_mass = {
        name: float(frame.abs().sum().sum()) for name, frame in contributions.items()
    }
    total_mass = sum(contribution_mass.values())
    effective = {
        name: (0.0 if total_mass == 0 else value / total_mass)
        for name, value in contribution_mass.items()
    }
    combined_mass = float(combined.abs().sum().sum())
    # A member that is missing at a cell contributed nothing there, so leave-one-out must
    # subtract 0 rather than propagate NaN; propagating would drop the cell from the norm
    # entirely and credit every member for exposure it did not supply.
    marginal = {
        name: (
            0.0
            if combined_mass == 0
            else (combined_mass - float(combined.sub(frame.fillna(0.0)).abs().sum().sum()))
            / combined_mass
        )
        for name, frame in contributions.items()
    }
    member_ids = tuple(sorted(members))
    return EnsembleResult(
        combined=combined,
        contributions=contributions,
        coefficients=selected,
        exposure=exposure_summary(combined),
        missing_by_member=missing,
        member_run_ids=member_ids,
        effective_weights=effective,
        netting=netting,
        member_similarity=_similarity(members),
        marginal_contribution=marginal,
        parent_lineage=member_ids,
    )


def combine_stored_weights(
    catalog: ResearchCatalog,
    *,
    members: Mapping[str, float],
    artifact_name: str = "weights",
) -> EnsembleResult:
    """Load only verified stored artifacts; no strategy object or callable is accepted."""
    frames: dict[str, pd.DataFrame] = {}
    for record_id in members:
        artifact = catalog.load_artifact(record_id, artifact_name)
        if not isinstance(artifact, pd.DataFrame):
            raise QlibxError(
                "PORTFOLIO",
                f"stored member artifact is not a DataFrame: {record_id}",
                expected="An ensemble member stores its weights as a table.",
                context={
                    "record_id": record_id,
                    "artifact": artifact_name,
                    "stored_type": type(artifact).__name__,
                },
            )
        frames[record_id] = artifact
    return combine_signed_weights(frames, coefficients=members)


def _similarity(members: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    names = sorted(members)
    flattened: dict[str, pd.Series] = {}
    for name in names:
        frame = members[name]
        flattened[name] = frame.stack().rename(name)
    return pd.concat(flattened.values(), axis=1, join="outer").corr()


def _shared_axis_name(
    members: Mapping[str, pd.DataFrame],
    *,
    axis: str,
) -> str | None:
    names = {
        getattr(frame, axis).name
        for frame in members.values()
        if getattr(frame, axis).name is not None
    }
    if len(names) > 1:
        raise QlibxError(
            "PORTFOLIO",
            f"ensemble members have incompatible {axis} semantics: {sorted(names)}",
            expected=(
                f"Every member labels its {axis} the same way; qlibx does not decide that two "
                "differently named axes mean the same thing."
            ),
            context={"axis": axis, "names": sorted(names)},
        )
    return next(iter(names), None)
