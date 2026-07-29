"""Answer whether a project can currently satisfy a Strategy manifest, and plan it.

This is the evidence-and-plan half of the capability cycle: the manifest declares what it
needs (``StrategyManifest.requirements``), this module reports what the project actually
holds against that declaration, and ``qlibx.requirements`` evaluates the two into a plan.
The plan is read-only by construction -- it never proposes or writes a mapping, because
choosing a field's meaning on the user's behalf is the failure it exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qlibx.catalog import ConfigDrivenDataLoader, DataCatalog
from qlibx.errors import QlibxError, requirement_gap
from qlibx.project import Project
from qlibx.requirements import CapabilityPlan, RequirementEvidence, evaluate_requirements, make_plan
from qlibx.serialization import digest_document

from .contracts import (
    StrategyBinding,
    StrategyInput,
    StrategyManifest,
    binding_document,
    manifest_document,
)


def plan_strategy_binding(
    project: Project,
    manifest: StrategyManifest,
    binding: StrategyBinding | None = None,
) -> CapabilityPlan:
    declaration = manifest.requirements()
    catalog = DataCatalog.from_project(project)
    loader = ConfigDrivenDataLoader(catalog)
    inventory = _registered_field_inventory(loader)
    evidence = tuple(
        _input_evidence(manifest, binding, item, catalog, inventory) for item in manifest.all_inputs
    )
    resolution = evaluate_requirements(declaration, evidence)
    return make_plan(
        declaration,
        resolution,
        parameters={
            "manifest": manifest_document(manifest),
            "binding": binding_document(binding) if binding is not None else None,
            "registered_field_inventory": inventory,
            "effective_config_id": effective_config_id(catalog, manifest, binding),
        },
        warnings=(
            "Field names are opaque until a user-approved binding records their semantics.",
            "The plan never proposes or writes a mapping.",
        ),
    )


def require_strategy_binding(
    project: Project,
    manifest: StrategyManifest,
    binding: StrategyBinding,
) -> CapabilityPlan:
    plan = plan_strategy_binding(project, manifest, binding)
    if not plan.ready:
        raise requirement_gap(plan.resolution.to_dict())
    return plan


def effective_config_id(
    catalog: DataCatalog,
    manifest: StrategyManifest,
    binding: StrategyBinding | None,
) -> str:
    return digest_document(
        {
            "catalog": catalog.fingerprint,
            "manifest": manifest.fingerprint,
            "binding": binding.fingerprint if binding is not None else None,
        }
    )


def _input_evidence(
    manifest: StrategyManifest,
    binding: StrategyBinding | None,
    contract: StrategyInput,
    catalog: DataCatalog,
    inventory: Mapping[str, Any],
) -> RequirementEvidence:
    requirement_id = f"input.{contract.role}"
    if binding is None:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            "No Strategy binding was selected.",
            details={"required_fields": [item.name for item in contract.fields]},
        )
    if (binding.strategy_id, binding.strategy_version) != (
        manifest.strategy_id,
        manifest.version,
    ):
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            "Binding Strategy ID/version does not match the manifest.",
            source=str(binding.source_path),
        )
    selected = binding.by_role().get(contract.role)
    if selected is None:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            f"Binding has no input role {contract.role!r}.",
            source=str(binding.source_path),
        )
    dataset = catalog.datasets.get(selected.registered_dataset)
    if dataset is None:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            f"Binding references unknown registered dataset {selected.registered_dataset!r}.",
            source=str(binding.source_path),
        )
    if dataset.kind != contract.pandas.kind:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            f"Dataset kind {dataset.kind!r} does not satisfy {contract.pandas.kind!r}.",
            source=selected.registered_dataset,
        )
    required = {item.name for item in contract.fields}
    mapped = set(selected.fields)
    if mapped != required:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            "Canonical mapping differs; "
            f"missing={sorted(required - mapped)}, extra={sorted(mapped - required)}.",
            source=str(binding.source_path),
        )
    dataset_inventory = inventory.get(selected.registered_dataset, {})
    fields = set(dataset_inventory.get("fields", ()))
    if dataset_inventory.get("error") is not None:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            f"Registered dataset inventory is unavailable: {dataset_inventory['error']}",
            source=selected.registered_dataset,
        )
    missing_sources = sorted(set(selected.fields.values()) - fields)
    if missing_sources:
        return RequirementEvidence(
            requirement_id,
            "registered_binding",
            False,
            f"Mapped registered fields do not exist: {missing_sources}.",
            source=selected.registered_dataset,
        )
    return RequirementEvidence(
        requirement_id,
        "registered_binding",
        True,
        f"Input {contract.role!r} resolves from {selected.registered_dataset!r}.",
        source=selected.registered_dataset,
        details={
            "canonical_fields": dict(selected.fields),
            "registered_fields": sorted(fields),
            "lookback_rows": manifest.lookback_rows,
        },
    )


def _registered_field_inventory(loader: ConfigDrivenDataLoader) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for name, spec in sorted(loader.catalog.datasets.items()):
        try:
            frame = loader.load_full_history(
                name, reason="registered field inventory for a read-only plan", limit=1
            )
            inventory[name] = {
                "kind": spec.kind,
                "fields": list(frame.columns),
                "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
            }
        except QlibxError as error:
            inventory[name] = {
                "kind": spec.kind,
                "fields": [],
                "dtypes": {},
                "error": error.to_dict(),
            }
    return inventory


__all__ = ["effective_config_id", "plan_strategy_binding", "require_strategy_binding"]
