"""Discoverable contracts and validation for trusted project-local extensions."""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from qlibx.alpha import OperationSpec
from qlibx.artifacts import ArtifactEnvelope
from qlibx.errors import QlibxError, unknown_name
from qlibx.project import Project
from qlibx.requirements import CapabilityRequirement


@dataclass(frozen=True, slots=True)
class ExtensionRef:
    extension_id: str
    contract: str
    contract_version: str
    source: Path
    callable_name: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class ExtensionContract:
    contract: str
    version: str
    purpose: str
    call_location: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    lifecycle: str
    allowed_side_effects: tuple[str, ...]
    validation: tuple[str, ...]
    compatibility: str
    composable: bool
    example_name: str
    requirements: tuple[CapabilityRequirement, ...] = ()


CONTRACTS: Mapping[str, ExtensionContract] = {
    "signal_transform": ExtensionContract(
        contract="signal_transform",
        version="1",
        purpose="Transform a bounded date-by-ticker signal without changing its axes.",
        call_location="after strategy signal and before budget/ensemble/execution",
        input_contract={
            "type": "pandas.DataFrame",
            "axis": "DatetimeIndex by ticker columns",
            "unit": "strategy-declared signal unit",
            "time_boundary": (
                "all available observations must be within the parent decision context"
            ),
        },
        output_contract={
            "type": "pandas.DataFrame",
            "axis": "exactly equal to input axes",
            "semantics": "transformed signal with missing observations preserved unless documented",
            "consumer": "alpha transform, budget, ensemble or recorder",
        },
        lifecycle="one detached call per bounded input; no shared mutable state",
        allowed_side_effects=(),
        validation=("input unchanged", "same axes", "finite-or-missing numeric output"),
        compatibility="contract version, axes, dtype and point-in-time boundary must match",
        composable=True,
        example_name="exponential_decay",
    ),
    "exposure_analyzer": ExtensionContract(
        contract="exposure_analyzer",
        version="1",
        purpose="Analyze a stored artifact without loading its producer.",
        call_location="analysis stage before report composition",
        input_contract={
            "type": "ArtifactEnvelope plus loaded portable payload",
            "time_boundary": "the envelope time range is authoritative",
        },
        output_contract={
            "type": "AnalysisSection",
            "semantics": "stored-artifact-derived metrics and warnings",
            "consumer": "report composition or raw user analysis",
        },
        lifecycle="pure analysis call over verified stored input",
        allowed_side_effects=(),
        validation=("section identity", "serializable data", "input artifact lineage"),
        compatibility="AnalysisSection schema version 1",
        composable=True,
        example_name="local_exposure_analyzer",
    ),
    "report_renderer": ExtensionContract(
        contract="report_renderer",
        version="1",
        purpose="Render a composed report document without recalculating analysis.",
        call_location="final presentation stage after section composition",
        input_contract={"type": "ReportDocument", "semantics": "calculated sections only"},
        output_contract={
            "type": "bytes or str",
            "semantics": "presentation output only",
            "consumer": "user-selected report path",
        },
        lifecycle="one deterministic render call; qlibx owns final file write",
        allowed_side_effects=(),
        validation=("bytes-or-text output", "input document unchanged"),
        compatibility="ReportDocument schema version 1",
        composable=False,
        example_name="local_text_renderer",
    ),
}


def extension_contract(name: str) -> ExtensionContract:
    if name not in CONTRACTS:
        raise unknown_name("ONBOARDING", "extension contract", name, CONTRACTS)
    return CONTRACTS[name]


def list_extension_contracts() -> tuple[ExtensionContract, ...]:
    return tuple(CONTRACTS[name] for name in sorted(CONTRACTS))


def load_extension(
    project: Project,
    *,
    extension_id: str,
    contract: str,
    contract_version: str,
    source: str | Path,
    callable_name: str,
) -> tuple[ExtensionRef, Callable[..., Any]]:
    declared = extension_contract(contract)
    if contract_version != declared.version:
        raise QlibxError(
            "ONBOARDING",
            f"extension contract version mismatch: installed={declared.version}, "
            f"requested={contract_version}",
            expected="The declared contract version is the one this qlibx installs.",
            context={
                "contract": contract,
                "installed": declared.version,
                "requested": contract_version,
            },
        )
    path = project.contained(source)
    if not path.is_relative_to(project.paths.extensions):
        raise QlibxError(
            "ONBOARDING",
            f"extension source is outside the configured extension root: {path}",
            expected="Extension source lives below the project's configured extension root.",
            context={"source": str(path), "extension_root": str(project.paths.extensions)},
        )
    if not path.is_file():
        raise QlibxError(
            "ONBOARDING",
            f"extension source does not exist: {path}",
            expected="The declared extension source is a file that exists.",
            context={"source": str(path)},
        )
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    module_name = f"qlibx_project_{extension_id}_{digest[:12]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise QlibxError(
            "ONBOARDING",
            f"extension cannot be loaded: {path}",
            expected="The extension source is an importable Python module.",
            context={"source": str(path)},
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    implementation = getattr(module, callable_name, None)
    if not callable(implementation):
        raise QlibxError(
            "ONBOARDING",
            f"extension callable does not exist: {callable_name}",
            expected="The module defines the declared callable at module level.",
            context={
                "source": str(path),
                "callable": callable_name,
                "defined": sorted(name for name in vars(module) if not name.startswith("_")),
            },
        )
    return (
        ExtensionRef(
            extension_id,
            contract,
            contract_version,
            path,
            callable_name,
            digest,
        ),
        implementation,
    )


def invoke_signal_transform(
    reference: ExtensionRef,
    implementation: Callable[..., Any],
    values: pd.DataFrame,
    **parameters: Any,
) -> pd.DataFrame:
    if reference.contract != "signal_transform" or reference.contract_version != "1":
        raise QlibxError(
            "ALPHA",
            "extension is not compatible with signal_transform version 1",
            expected="A signal transform declares contract 'signal_transform' version 1.",
            context={"contract": reference.contract, "version": reference.contract_version},
        )
    detached = values.copy(deep=True)
    before = detached.copy(deep=True)
    result = implementation(detached, **parameters)
    pd.testing.assert_frame_equal(detached, before)
    if not isinstance(result, pd.DataFrame):
        raise TypeError("signal_transform must return a pandas DataFrame")
    if not result.index.equals(values.index) or not result.columns.equals(values.columns):
        raise QlibxError(
            "ALPHA",
            "signal_transform output axes must exactly match input axes",
            expected="A transform returns the axes it was given; it cannot add or drop rows.",
            context={
                "added_rows": sorted(str(name) for name in result.index.difference(values.index)),
                "dropped_rows": sorted(str(name) for name in values.index.difference(result.index)),
            },
        )
    numeric = result.apply(pd.to_numeric, errors="coerce")
    invalid = result.notna() & numeric.isna()
    if invalid.any().any():
        raise QlibxError(
            "ALPHA",
            "signal_transform output must be numeric or missing",
            expected="Every returned cell is a number or missing; missing input stays missing.",
            context={
                "columns_with_non_numeric": sorted(
                    str(name) for name in invalid.columns[invalid.any()]
                )
            },
        )
    return result


def signal_transform_operation(
    reference: ExtensionRef,
    implementation: Callable[..., Any],
    *,
    summary: str = "Project-local signal_transform extension.",
    parameters: Mapping[str, str] | None = None,
    required_parameters: tuple[str, ...] = (),
    requirements: tuple[CapabilityRequirement, ...] = (),
    version: str = "1",
) -> OperationSpec:
    """Adapt a validated project-local ``signal_transform`` into an alpha operation.

    The returned spec can be passed to ``qlibx.alpha.register_operation``, after which
    the extension composes with built-ins through ``apply_pipeline`` and contributes the
    same lineage, including its source digest. Every call still goes through
    ``invoke_signal_transform``, so the contract is validated on each application.
    """
    if reference.contract != "signal_transform" or reference.contract_version != version:
        raise QlibxError(
            "ALPHA",
            f"extension is not compatible with signal_transform version {version}",
            expected=(
                f"A promoted operation declares contract 'signal_transform' version {version}."
            ),
            context={"contract": reference.contract, "version": reference.contract_version},
        )

    def apply(values: pd.DataFrame, **call_parameters: Any) -> pd.DataFrame:
        return invoke_signal_transform(reference, implementation, values, **call_parameters)

    return OperationSpec(
        name=reference.extension_id,
        operation_id=f"project.{reference.extension_id}",
        version=version,
        axis="date_by_ticker",
        tie_behavior="extension_defined",
        nan_behavior="preserved_unless_the_extension_documents_otherwise",
        minimum_observations=None,
        group_missing_behavior="not_applicable",
        dtype="float64",
        summary=summary,
        apply=apply,
        parameters=dict(parameters or {}),
        required_parameters=required_parameters,
        requirements=requirements,
        implementation=f"extension:{reference.contract}/{reference.contract_version}",
        implementation_digest=reference.source_digest,
    )


def invoke_exposure_analyzer(
    reference: ExtensionRef,
    implementation: Callable[..., Any],
    envelope: ArtifactEnvelope,
    payload: Any,
) -> Any:
    if reference.contract != "exposure_analyzer" or reference.contract_version != "1":
        raise QlibxError(
            "REPORTING",
            "extension is not compatible with exposure_analyzer version 1",
            expected="An analyzer declares contract 'exposure_analyzer' version 1.",
            context={"contract": reference.contract, "version": reference.contract_version},
        )
    result = implementation(envelope, payload)
    if not all(hasattr(result, name) for name in ("section_id", "version", "data")):
        raise TypeError("exposure_analyzer must return an AnalysisSection-compatible value")
    return result


def invoke_report_renderer(
    reference: ExtensionRef,
    implementation: Callable[..., Any],
    document: Any,
) -> bytes:
    if reference.contract != "report_renderer" or reference.contract_version != "1":
        raise QlibxError(
            "REPORTING",
            "extension is not compatible with report_renderer version 1",
            expected="A renderer declares contract 'report_renderer' version 1.",
            context={"contract": reference.contract, "version": reference.contract_version},
        )
    result = implementation(document)
    if isinstance(result, str):
        return result.encode("utf-8")
    if isinstance(result, bytes):
        return result
    raise TypeError("report_renderer must return bytes or str")
