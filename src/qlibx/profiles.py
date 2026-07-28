"""Explicit logical-data to Qlib execution profile planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from qlibx.catalog import DataCatalog
from qlibx.config import read_yaml, require_mapping, require_string
from qlibx.errors import QlibxError
from qlibx.project import Project

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


@dataclass(frozen=True, slots=True)
class ExecutionProfilePlan:
    profile_id: str
    target_semantics: TargetSemantics
    config_path: str
    clock: dict[str, str]
    roles: dict[str, str]
    required_roles: tuple[str, ...]
    missing_roles: tuple[str, ...]
    unknown_datasets: tuple[str, ...]
    non_matrix_datasets: tuple[str, ...]
    role_contracts: dict[str, dict[str, str | None]]
    derived_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_features: tuple[str, ...]
    ready: bool
    read_only: bool = True
    mutates: tuple[str, ...] = ()


def execution_profile_requirements(
    target_semantics: TargetSemantics = "long_only",
) -> dict[str, object]:
    if target_semantics not in {"long_only", "signed_weight", "enhanced_index"}:
        raise QlibxError(
            "QLIBX_TARGET_SEMANTICS_UNSUPPORTED",
            f"Unsupported target semantics: {target_semantics}",
            action="Choose long_only, signed_weight, or enhanced_index.",
        )
    roles = (*COMMON_ROLES, *(SIGNED_ROLES if target_semantics == "signed_weight" else ()))
    return {
        "schema_version": 1,
        "profile": "daily_close_v1",
        "target_semantics": target_semantics,
        "required_roles": roles,
        "default_clock": {
            "signal_cutoff": "t_minus_1_close",
            "decision_time": "t_close",
            "execution_time": "t_close",
            "valuation_time": "t_close",
        },
        "mapping_rule": "Every role maps to an explicitly declared logical matrix dataset.",
        "derived_fields": [],
        "agent_action": (
            "Discuss each role and clock with the user. qlibx does not derive prices, correction "
            "factors, universes, tradability, shortability, or benchmark weights."
        ),
        "unsupported_features": [
            "native borrow/margin/recall/forced-buy-in/borrow-fee modeling",
            "non-unit position adjustment factors inside qlibx",
        ],
    }


def plan_execution_profile(
    project: Project,
    config_path: str | Path = "config/qlibx/execution.yaml",
) -> ExecutionProfilePlan:
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
    requirements = execution_profile_requirements(semantics)  # type: ignore[arg-type]
    clock = {
        str(key): str(value) for key, value in require_mapping(raw.get("clock"), "clock").items()
    }
    roles = {
        str(key): str(value)
        for key, value in require_mapping(raw.get("datasets"), "datasets").items()
    }
    required_roles = tuple(str(item) for item in requirements["required_roles"])
    missing_roles = tuple(sorted(set(required_roles) - set(roles)))
    catalog = DataCatalog.from_project(project)
    unknown = tuple(
        sorted({roles[role] for role in required_roles if role in roles} - set(catalog.datasets))
    )
    non_matrix = tuple(
        sorted(
            dataset
            for dataset in {roles[role] for role in required_roles if role in roles}
            if dataset in catalog.datasets and catalog.datasets[dataset].kind != "matrix"
        )
    )
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
    warnings: list[str] = [
        "All mapped values are user-defined data. qlibx does not adjust or normalize them.",
        (
            "The daily_close_v1 default observes data available by t-1 close and indexes "
            "execution at event date t."
        ),
    ]
    expected_clock = requirements["default_clock"]
    clock_mismatch = profile_id == "daily_close_v1" and clock != expected_clock
    if clock_mismatch:
        warnings.append(
            "daily_close_v1 clock differs from the installed default; use another explicit "
            "profile_id or correct it."
        )
    ready = not (missing_roles or unknown or non_matrix or clock_mismatch)
    return ExecutionProfilePlan(
        profile_id=profile_id,
        target_semantics=semantics,  # type: ignore[arg-type]
        config_path=str(path),
        clock=clock,
        roles=roles,
        required_roles=required_roles,
        missing_roles=missing_roles,
        unknown_datasets=unknown,
        non_matrix_datasets=non_matrix,
        role_contracts=role_contracts,
        derived_fields=(),
        warnings=tuple(warnings),
        unsupported_features=tuple(str(item) for item in requirements["unsupported_features"]),
        ready=ready,
    )
