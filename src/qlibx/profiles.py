"""Public capability requirements and planning for Qlib execution profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from qlibx.catalog import DataCatalog
from qlibx.config import read_yaml, require_mapping, require_string
from qlibx.errors import QlibxError, requirement_gap
from qlibx.project import Project
from qlibx.requirements import (
    CapabilityPlan,
    CapabilityRequirement,
    CapabilityRequirements,
    DerivationAlternative,
    RequirementEvidence,
    evaluate_requirements,
    make_plan,
)

TargetSemantics = Literal["long_only", "signed_weight", "enhanced_index"]

COMMON_ROLES = (
    "execution_price",
    "valuation_price",
    "universe",
    "tradable",
    "volume",
    "benchmark_weight",
)
SIGNED_ROLES = ("observed", "shortable")
DEFAULT_CLOCK = {
    "signal_cutoff": "t_minus_1_close",
    "decision_time": "t_close",
    "execution_time": "t_close",
    "valuation_time": "t_close",
}
UNSUPPORTED_FEATURES = (
    "native borrow/margin/recall/forced-buy-in/borrow-fee modeling",
    "non-unit position adjustment factors inside qlibx",
)


def _role_requirement(role: str) -> CapabilityRequirement:
    return CapabilityRequirement(
        requirement_id=role,
        role=role,
        meaning=f"Project-declared logical matrix for the Qlib {role} role.",
        axis="event_time_by_ticker",
        unit="project_declared",
        currency="project_declared_or_not_applicable",
        purpose=f"Supply the {role} input to the configured Qlib execution profile.",
        satisfaction_rule=("The role maps to a registered logical dataset whose kind is matrix."),
        availability=(
            "The logical dataset declares an availability field and is bounded by the "
            "profile clock."
        ),
        mandatory=True,
        unavailable_effect="The execution profile cannot be used.",
        alternatives=(
            DerivationAlternative(
                alternative_id="registered_logical_matrix",
                description="Map the role to an explicitly registered logical matrix dataset.",
                required_inputs=(role,),
                derivation="direct project configuration",
            ),
        ),
        next_commands=(
            "qlibx data catalog --root <project>",
            "qlibx qlib plan --root <project> --config config/qlibx/execution.yaml",
        ),
    )


def _clock_requirement() -> CapabilityRequirement:
    return CapabilityRequirement(
        requirement_id="execution_clock",
        role="execution_clock",
        meaning="Explicit signal, decision, execution, and valuation clock.",
        axis="time",
        unit="timestamp_semantics",
        currency="not_applicable",
        purpose="Bound every execution input at the declared decision time.",
        satisfaction_rule=(
            "daily_close_v1 uses the installed default clock; another profile ID declares its "
            "clock explicitly."
        ),
        availability="The signal cutoff must not be later than the decision time.",
        mandatory=True,
        unavailable_effect="The execution profile clock is ambiguous or incompatible.",
        alternatives=(
            DerivationAlternative(
                alternative_id="declared_profile_clock",
                description="Use an explicit clock compatible with the selected profile ID.",
                required_inputs=("clock",),
                derivation="direct project configuration",
            ),
        ),
        next_commands=(
            "qlibx qlib requirements --target-semantics <semantics>",
            "qlibx qlib plan --root <project> --config config/qlibx/execution.yaml",
        ),
    )


def execution_profile_requirements(
    target_semantics: TargetSemantics = "long_only",
) -> CapabilityRequirements:
    if target_semantics not in {"long_only", "signed_weight", "enhanced_index"}:
        raise QlibxError(
            "QLIBX_TARGET_SEMANTICS_UNSUPPORTED",
            f"Unsupported target semantics: {target_semantics}",
            action="Choose long_only, signed_weight, or enhanced_index.",
        )
    roles = (*COMMON_ROLES, *(SIGNED_ROLES if target_semantics == "signed_weight" else ()))
    return CapabilityRequirements(
        capability_id="qlibx.execution.daily_close",
        capability_version="1",
        summary="Map explicit project datasets and clocks to the Qlib execution lifecycle.",
        requirements=(*(_role_requirement(role) for role in roles), _clock_requirement()),
        parameters={
            "profile_id": "daily_close_v1",
            "target_semantics": target_semantics,
            "default_clock": dict(DEFAULT_CLOCK),
            "mapping_rule": ("Every role maps to an explicitly declared logical matrix dataset."),
            "derived_fields": [],
        },
    )


def plan_execution_profile(
    project: Project,
    config_path: str | Path = "config/qlibx/execution.yaml",
) -> CapabilityPlan:
    path = project.contained(config_path)
    if not path.is_relative_to(project.paths.config):
        raise QlibxError(
            "QLIBX_EXECUTION_CONFIG_OUTSIDE_ROOT",
            f"Execution profile is outside config root: {path}",
            action="Keep the user-authored profile below config/qlibx.",
        )
    raw = read_yaml(path)
    if raw.get("schema_version") != 1:
        raise QlibxError(
            "QLIBX_EXECUTION_PROFILE_SCHEMA_UNSUPPORTED",
            "execution profile schema_version must be 1",
            action="Use the installed execution profile schema.",
        )
    profile_id = require_string(raw.get("profile_id"), "profile_id")
    semantics = require_string(raw.get("target_semantics"), "target_semantics")
    declaration = execution_profile_requirements(semantics)  # type: ignore[arg-type]
    clock = {
        str(key): str(value) for key, value in require_mapping(raw.get("clock"), "clock").items()
    }
    roles = {
        str(key): str(value)
        for key, value in require_mapping(raw.get("datasets"), "datasets").items()
    }
    catalog = DataCatalog.from_project(project)
    role_contracts = {
        role: {
            "dataset": dataset,
            "time_field": catalog.datasets[dataset].time_field,
            "event_time_field": (
                catalog.datasets[dataset].time_field
                if catalog.datasets[dataset].time_field
                != catalog.datasets[dataset].availability_field
                else None
            ),
            "availability_field": catalog.datasets[dataset].availability_field,
            "value_field": catalog.datasets[dataset].values,
        }
        for role, dataset in roles.items()
        if dataset in catalog.datasets
    }
    evidence: list[RequirementEvidence] = []
    for requirement in declaration.requirements:
        if requirement.requirement_id == "execution_clock":
            clock_matches = profile_id != "daily_close_v1" or clock == DEFAULT_CLOCK
            evidence.append(
                RequirementEvidence(
                    requirement_id="execution_clock",
                    alternative_id="declared_profile_clock",
                    satisfied=clock_matches,
                    reason=(
                        "The declared clock is compatible with the selected profile."
                        if clock_matches
                        else "daily_close_v1 clock differs from the installed default."
                    ),
                    source="execution_profile",
                    details={"profile_id": profile_id, "clock": clock},
                )
            )
            continue
        role = requirement.role
        dataset = roles.get(role)
        if dataset is None:
            satisfied = False
            reason = f"Required role {role!r} is not mapped in the execution profile."
            details: dict[str, object] = {}
        elif dataset not in catalog.datasets:
            satisfied = False
            reason = f"Mapped dataset {dataset!r} is not registered in the logical catalog."
            details = {"dataset": dataset}
        elif catalog.datasets[dataset].kind != "matrix":
            satisfied = False
            reason = f"Mapped dataset {dataset!r} is not a matrix dataset."
            details = {"dataset": dataset, "kind": catalog.datasets[dataset].kind}
        else:
            satisfied = True
            reason = f"Role {role!r} is mapped to registered matrix dataset {dataset!r}."
            details = dict(role_contracts[role])
        evidence.append(
            RequirementEvidence(
                requirement_id=requirement.requirement_id,
                alternative_id="registered_logical_matrix",
                satisfied=satisfied,
                reason=reason,
                source="project_catalog",
                details=details,
            )
        )
    resolution = evaluate_requirements(declaration, tuple(evidence))
    warnings = [
        "All mapped values are user-defined data. qlibx does not adjust or normalize them.",
        (
            "The daily_close_v1 default observes data available by t-1 close and indexes "
            "execution at event date t."
        ),
    ]
    if "execution_clock" in resolution.missing_requirements:
        warnings.append(
            "daily_close_v1 clock differs from the installed default; use another explicit "
            "profile_id or correct it."
        )
    return make_plan(
        declaration,
        resolution,
        parameters={
            "profile_id": profile_id,
            "target_semantics": semantics,
            "config_path": str(path),
            "clock": clock,
            "roles": roles,
            "role_contracts": role_contracts,
            "derived_fields": [],
        },
        warnings=tuple(warnings),
        unsupported_features=UNSUPPORTED_FEATURES,
    )


def require_execution_profile(
    project: Project,
    config_path: str | Path = "config/qlibx/execution.yaml",
) -> CapabilityPlan:
    """Return a ready profile plan or fail with the same structured resolution."""
    plan = plan_execution_profile(project, config_path)
    if not plan.ready:
        raise requirement_gap(plan.resolution.to_dict())
    return plan


__all__ = [
    "COMMON_ROLES",
    "DEFAULT_CLOCK",
    "SIGNED_ROLES",
    "TargetSemantics",
    "execution_profile_requirements",
    "plan_execution_profile",
    "require_execution_profile",
]
