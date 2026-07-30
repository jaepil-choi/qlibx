"""Operation registry, dispatch, and pipeline composition.

Adding an operation means registering one ``OperationSpec``; nothing here changes.
Dispatch, lineage, parameter validation, and the documentation surface all read from
the same registry, so a built-in, a project-local callable, and an extension-backed
transform are indistinguishable to callers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from qlibx.errors import requirement_gap, unknown_name
from qlibx.requirements import (
    CapabilityPlan,
    CapabilityRequirement,
    CapabilityRequirements,
    plan_capability,
    supplied_roles_probe,
)

from .contracts import OperationContract, TransformResult


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Declared semantics plus the implementation of one deterministic operation.

    ``apply`` is called as ``apply(values, **parameters)``, or with a ``groups`` argument
    when the common requirement declaration contains the ``group_label`` role.
    ``resolve_minimum_observations`` lets a parameterized window override the declared
    default so lineage records the count actually required.
    """

    name: str
    operation_id: str
    version: str
    axis: str
    tie_behavior: str
    nan_behavior: str
    minimum_observations: int | None
    group_missing_behavior: str
    dtype: str
    summary: str
    apply: Callable[..., pd.DataFrame]
    parameters: Mapping[str, str] = field(default_factory=dict)
    required_parameters: tuple[str, ...] = ()
    requirements: tuple[CapabilityRequirement, ...] = ()
    selection_behavior: str = "not_applicable"
    neutrality_warning: str | None = None
    implementation: str = "builtin"
    implementation_digest: str | None = None
    resolve_minimum_observations: Callable[[Mapping[str, Any]], int | None] | None = None

    def contract(self, parameters: Mapping[str, Any]) -> OperationContract:
        minimum = self.minimum_observations
        if self.resolve_minimum_observations is not None:
            minimum = self.resolve_minimum_observations(parameters)
        return OperationContract(
            operation_id=self.operation_id,
            version=self.version,
            axis=self.axis,
            tie_behavior=self.tie_behavior,
            nan_behavior=self.nan_behavior,
            minimum_observations=None if minimum is None else int(minimum),
            group_missing_behavior=self.group_missing_behavior,
            dtype=self.dtype,
            parameters=dict(parameters),
            summary=self.summary,
            selection_behavior=self.selection_behavior,
            implementation=self.implementation,
            implementation_digest=self.implementation_digest,
        )

    def describe(self) -> dict[str, Any]:
        """Return the agent-facing contract without executing the operation."""
        return {
            "name": self.name,
            "operation_id": self.operation_id,
            "version": self.version,
            "summary": self.summary,
            "axis": self.axis,
            "tie_behavior": self.tie_behavior,
            "nan_behavior": self.nan_behavior,
            "minimum_observations": self.minimum_observations,
            "group_missing_behavior": self.group_missing_behavior,
            "selection_behavior": self.selection_behavior,
            "dtype": self.dtype,
            "parameters": dict(self.parameters),
            "required_parameters": list(self.required_parameters),
            "requirements": [asdict(item) for item in self.requirements],
            "neutrality_warning": self.neutrality_warning,
            "implementation": self.implementation,
        }


class OperationRegistry:
    """Name-to-``OperationSpec`` registry backing dispatch, lineage, and documentation."""

    def __init__(self) -> None:
        self._specs: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec, *, replace_existing: bool = False) -> OperationSpec:
        if spec.name in self._specs and not replace_existing:
            raise ValueError(f"alpha operation is already registered: {spec.name}")
        missing = sorted(set(spec.required_parameters) - set(spec.parameters))
        if missing:
            raise ValueError(f"operation {spec.name} requires undeclared parameters: {missing}")
        self._specs[spec.name] = spec
        return spec

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)

    def get(self, name: str) -> OperationSpec:
        try:
            return self._specs[name]
        except KeyError as error:
            raise unknown_name("ALPHA", "alpha operation", name, self._specs) from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def describe(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._specs[name].describe() for name in self.names())


OPERATIONS = OperationRegistry()


def register_operation(spec: OperationSpec, *, replace_existing: bool = False) -> OperationSpec:
    """Register a built-in, project-local, or extension-backed signal operation."""
    return OPERATIONS.register(spec, replace_existing=replace_existing)


def operation_spec(name: str) -> OperationSpec:
    return OPERATIONS.get(name)


def list_operations() -> tuple[dict[str, Any], ...]:
    """Return every installed operation contract for help, schema, and skill output."""
    return OPERATIONS.describe()


def operation_contract(name: str, **parameters: Any) -> OperationContract:
    """Return the versioned semantics that become transform lineage."""
    return OPERATIONS.get(name).contract(parameters)


def operation_requirements(name: str) -> CapabilityRequirements:
    spec = OPERATIONS.get(name)
    return CapabilityRequirements(
        capability_id=spec.operation_id,
        capability_version=spec.version,
        summary=spec.summary,
        requirements=spec.requirements,
        parameters={"operation_name": spec.name},
    )


def plan_operation(
    name: str,
    *,
    provided_inputs: Iterable[str] = (),
) -> CapabilityPlan:
    """Plan one operation from explicit input roles without executing it."""
    provided = sorted(set(provided_inputs))
    return plan_capability(
        operation_requirements(name),
        supplied_roles_probe(provided),
        parameters={"operation_name": name, "provided_inputs": provided},
    )


def _validate_parameters(spec: OperationSpec, parameters: Mapping[str, Any]) -> None:
    unknown = sorted(set(parameters) - set(spec.parameters))
    if unknown:
        raise ValueError(
            f"operation {spec.name} does not accept parameters {unknown}; "
            f"declared: {sorted(spec.parameters)}"
        )
    missing = sorted(set(spec.required_parameters) - set(parameters))
    if missing:
        raise ValueError(f"operation {spec.name} requires parameters {missing}")


def _apply_spec(
    spec: OperationSpec,
    values: pd.DataFrame,
    groups: pd.DataFrame | None,
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    _validate_parameters(spec, parameters)
    provided_inputs = {
        requirement.role
        for requirement in spec.requirements
        if requirement.role in parameters and parameters[requirement.role] is not None
    }
    if groups is not None:
        provided_inputs.add("group_label")
    plan = plan_operation(spec.name, provided_inputs=provided_inputs)
    if not plan.ready:
        raise requirement_gap("ALPHA", plan.resolution.to_dict())
    needs_groups = any(item.role == "group_label" for item in spec.requirements)
    if needs_groups:
        assert groups is not None
        return spec.apply(values, groups=groups, **parameters)
    return spec.apply(values, **parameters)


def apply_transform(
    name: str,
    values: pd.DataFrame,
    *,
    groups: pd.DataFrame | None = None,
    **parameters: Any,
) -> TransformResult:
    """Apply one registered operation and return its explicit lineage."""
    spec = OPERATIONS.get(name)
    transformed = _apply_spec(spec, values, groups, parameters)
    return TransformResult(transformed, (spec.contract(parameters),), spec.neutrality_warning)


@dataclass(frozen=True, slots=True)
class PipelineStep:
    name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


StepLike = PipelineStep | str | tuple[str, Mapping[str, Any]]


def _as_step(step: StepLike) -> PipelineStep:
    if isinstance(step, PipelineStep):
        return step
    if isinstance(step, str):
        return PipelineStep(step)
    name, parameters = step
    return PipelineStep(name, dict(parameters))


def apply_pipeline(
    values: pd.DataFrame,
    steps: Sequence[StepLike] | Iterable[StepLike],
    *,
    groups: pd.DataFrame | None = None,
) -> TransformResult:
    """Compose registered operations in order and accumulate one lineage chain.

    Every step contributes its own ``OperationContract``, so a chained result records
    exactly which operations, versions, and parameters produced it.
    """
    ordered = [_as_step(step) for step in steps]
    if not ordered:
        raise ValueError("pipeline requires at least one step")
    current = values
    lineage: list[OperationContract] = []
    warnings: list[str] = []
    for step in ordered:
        spec = OPERATIONS.get(step.name)
        current = _apply_spec(spec, current, groups, step.parameters)
        lineage.append(spec.contract(step.parameters))
        if spec.neutrality_warning is not None and spec.neutrality_warning not in warnings:
            warnings.append(spec.neutrality_warning)
    return TransformResult(current, tuple(lineage), " ".join(warnings) if warnings else None)


__all__ = [
    "OPERATIONS",
    "OperationRegistry",
    "OperationSpec",
    "PipelineStep",
    "StepLike",
    "apply_pipeline",
    "apply_transform",
    "list_operations",
    "operation_contract",
    "operation_requirements",
    "operation_spec",
    "plan_operation",
    "register_operation",
]
