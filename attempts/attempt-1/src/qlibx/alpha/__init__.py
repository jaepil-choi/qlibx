"""Deterministic signed-alpha transforms, budget policies, and diagnostics.

Signal operations and weight-scaling (budget) policies are both declared in registries
rather than in branching dispatch code. Adding an operation or a scaling rule means
registering one ``OperationSpec`` or ``BudgetPolicySpec``; dispatch, lineage, and the
documentation surface follow automatically. Project-local code and validated
``signal_transform`` extensions register through the same door, so a custom operation
composes with built-ins and carries the same lineage.

Layout::

    contracts.py    value objects shared by registry and operations
    registry.py     OperationSpec, dispatch, pipeline composition
    operations/     built-in operations, grouped by the axis they act on
    budget.py       weight-scaling policies
    exposure.py     exposure measurement

This package re-exports the whole public surface, so ``from qlibx.alpha import X``
keeps working regardless of which file ``X`` lives in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .budget import (
    BUDGET_POLICIES,
    BudgetPolicyRegistry,
    BudgetPolicySpec,
    BudgetResult,
    apply_budget,
    budget_policy,
    list_budget_policies,
    register_budget_policy,
    rescale_budget,
)
from .contracts import NEUTRALITY_WARNING, OperationContract, TransformResult
from .exposure import (
    EXPOSURE_METRICS,
    ExposureArtifact,
    ExposureMetric,
    ExposureSummary,
    analyze_exposure,
    exposure_requirements,
    exposure_summary,
    plan_exposure,
)

# Importing the operations package registers every built-in.
from .operations import (
    clip,
    cross_sectional_demean,
    cross_sectional_rank,
    cross_sectional_zscore,
    group_demean,
    hump,
    lag,
    linear_decay,
    per_name_cap,
    rolling_mean,
    rolling_std,
    top_bottom,
    winsorize,
)
from .registry import (
    OPERATIONS,
    OperationRegistry,
    OperationSpec,
    PipelineStep,
    apply_pipeline,
    apply_transform,
    list_operations,
    operation_contract,
    operation_requirements,
    operation_spec,
    plan_operation,
    register_operation,
)

# Backwards-compatible read-only view of the declared semantics.
OPERATION_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    spec["name"]: spec for spec in OPERATIONS.describe()
}

__all__ = [
    "BUDGET_POLICIES",
    "EXPOSURE_METRICS",
    "NEUTRALITY_WARNING",
    "OPERATIONS",
    "OPERATION_CONTRACTS",
    "BudgetPolicyRegistry",
    "BudgetPolicySpec",
    "BudgetResult",
    "ExposureArtifact",
    "ExposureMetric",
    "ExposureSummary",
    "OperationContract",
    "OperationRegistry",
    "OperationSpec",
    "PipelineStep",
    "TransformResult",
    "analyze_exposure",
    "apply_budget",
    "apply_pipeline",
    "apply_transform",
    "budget_policy",
    "clip",
    "cross_sectional_demean",
    "cross_sectional_rank",
    "cross_sectional_zscore",
    "exposure_requirements",
    "exposure_summary",
    "group_demean",
    "hump",
    "lag",
    "linear_decay",
    "list_budget_policies",
    "list_operations",
    "operation_contract",
    "operation_requirements",
    "operation_spec",
    "per_name_cap",
    "plan_exposure",
    "plan_operation",
    "register_budget_policy",
    "register_operation",
    "rescale_budget",
    "rolling_mean",
    "rolling_std",
    "top_bottom",
    "winsorize",
]
