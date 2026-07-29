"""Project-owned Strategy manifests, bindings, and pandas input resolution."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import pandas as pd

from qlibx.catalog import ConfigDrivenDataLoader, DataCatalog, require_matrix_axes
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
from qlibx.serialization import digest_dataset, digest_document, digest_file

PandasKind = Literal["table", "matrix"]
StrategyOutputKind = Literal["signal", "weight", "order", "payload"]


@dataclass(frozen=True, slots=True)
class StrategyImplementation:
    source: str
    callable: str


@dataclass(frozen=True, slots=True)
class StrategyField:
    name: str
    meaning: str
    dtype: str
    unit: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class PandasInputContract:
    kind: PandasKind
    index: tuple[str, ...]
    dtype: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyInput:
    role: str
    meaning: str
    pandas: PandasInputContract
    fields: tuple[StrategyField, ...] = ()
    inherited: bool = False


@dataclass(frozen=True, slots=True)
class StrategyManifest:
    strategy_id: str
    version: str
    name: str
    contract: str
    implementation: StrategyImplementation
    parameters: Mapping[str, Any]
    lookback_rows: int
    inputs: tuple[StrategyInput, ...]
    output_kind: StrategyOutputKind
    source_path: Path
    fingerprint: str

    @property
    def all_inputs(self) -> tuple[StrategyInput, ...]:
        return (base_universe_input(), *self.inputs)

    def requirements(self) -> CapabilityRequirements:
        return CapabilityRequirements(
            capability_id=f"strategy.{self.strategy_id}",
            capability_version=self.version,
            summary=f"Resolve registered pandas inputs for Strategy {self.name!r}.",
            requirements=tuple(_input_requirement(self, item) for item in self.all_inputs),
            parameters={
                "contract": self.contract,
                "lookback": {"kind": "rows", "value": self.lookback_rows},
                "output": {"kind": self.output_kind},
                "inputs": [_input_dict(item) for item in self.all_inputs],
            },
        )


@dataclass(frozen=True, slots=True)
class StrategyBindingInput:
    role: str
    registered_dataset: str
    fields: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategyBinding:
    binding_id: str
    strategy_id: str
    strategy_version: str
    inputs: tuple[StrategyBindingInput, ...]
    source_path: Path
    fingerprint: str

    def by_role(self) -> dict[str, StrategyBindingInput]:
        return {item.role: item for item in self.inputs}


@dataclass(frozen=True, slots=True)
class ResolvedStrategyInputs:
    strategy_id: str
    strategy_version: str
    binding_id: str
    decision_time: pd.Timestamp
    inputs: Mapping[str, pd.DataFrame]
    effective_config_id: str


def base_universe_input() -> StrategyInput:
    """The mandatory input inherited by every qlibx pandas Strategy."""
    return StrategyInput(
        role="universe",
        meaning="Point-in-time research universe membership.",
        pandas=PandasInputContract(kind="matrix", index=("observation_time",), dtype="bool"),
        inherited=True,
    )


def load_strategy_manifest(project: Project, strategy: str | Path) -> StrategyManifest:
    path = _config_path(project, strategy, "strategies")
    raw = read_yaml(path)
    _keys(raw, {"schema_version", "contract", "strategy"}, str(path))
    _schema(raw, path)
    contract = require_string(raw.get("contract"), "contract")
    if contract != "qlibx.pandas_strategy":
        raise QlibxError(
            "QLIBX_STRATEGY_CONTRACT_UNSUPPORTED",
            f"Unsupported Strategy contract: {contract!r}",
            action="Use qlibx.pandas_strategy.",
        )
    value = require_mapping(raw.get("strategy"), "strategy")
    _keys(
        value,
        {"id", "version", "name", "implementation", "parameters", "lookback", "inputs", "output"},
        "strategy",
    )
    implementation_raw = require_mapping(value.get("implementation"), "implementation")
    _keys(implementation_raw, {"source", "callable"}, "implementation")
    implementation = StrategyImplementation(
        source=require_string(implementation_raw.get("source"), "implementation.source"),
        callable=require_string(implementation_raw.get("callable"), "implementation.callable"),
    )
    parameters = require_mapping(value.get("parameters", {}), "parameters")
    lookback = require_mapping(value.get("lookback"), "lookback")
    _keys(lookback, {"kind", "value"}, "lookback")
    if lookback.get("kind") != "rows":
        raise QlibxError(
            "QLIBX_STRATEGY_LOOKBACK_UNSUPPORTED",
            "Strategy lookback.kind must be rows",
            action="Use a fixed positive row lookback.",
        )
    rows = lookback.get("value")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
        raise QlibxError(
            "QLIBX_STRATEGY_LOOKBACK_INVALID",
            "Strategy lookback.value must be a positive integer",
            action="Declare the fixed number of rows supplied at every decision.",
        )
    inputs_raw = require_mapping(value.get("inputs"), "inputs")
    if "universe" in inputs_raw:
        raise QlibxError(
            "QLIBX_STRATEGY_UNIVERSE_REDECLARED",
            "universe is inherited from qlibx.pandas_strategy",
            action="Remove universe from the manifest and bind it in the binding YAML.",
        )
    inputs = tuple(_strategy_input(role, item) for role, item in inputs_raw.items())
    if not inputs:
        raise QlibxError(
            "QLIBX_STRATEGY_INPUTS_EMPTY",
            "Strategy must declare at least one Strategy-specific pandas input",
            action="Declare the canonical pandas data used by the Strategy.",
        )
    output = require_mapping(value.get("output"), "output")
    _keys(output, {"kind"}, "output")
    output_kind = require_string(output.get("kind"), "output.kind")
    if output_kind not in {"signal", "weight", "order", "payload"}:
        raise QlibxError(
            "QLIBX_STRATEGY_OUTPUT_INVALID",
            f"Unsupported Strategy output kind: {output_kind!r}",
            action="Use signal, weight, order, or payload.",
        )
    return StrategyManifest(
        strategy_id=require_string(value.get("id"), "strategy.id"),
        version=require_string(value.get("version"), "strategy.version"),
        name=require_string(value.get("name"), "strategy.name"),
        contract=contract,
        implementation=implementation,
        parameters=MappingProxyType(dict(parameters)),
        lookback_rows=rows,
        inputs=inputs,
        output_kind=output_kind,
        source_path=path,
        fingerprint=digest_document(raw),
    )


def load_strategy_binding(project: Project, binding: str | Path) -> StrategyBinding:
    path = _config_path(project, binding, "bindings")
    raw = read_yaml(path)
    _keys(raw, {"schema_version", "binding"}, str(path))
    _schema(raw, path)
    value = require_mapping(raw.get("binding"), "binding")
    _keys(value, {"id", "strategy", "inputs"}, "binding")
    strategy = require_mapping(value.get("strategy"), "binding.strategy")
    _keys(strategy, {"id", "version"}, "binding.strategy")
    inputs_raw = require_mapping(value.get("inputs"), "binding.inputs")
    inputs: list[StrategyBindingInput] = []
    for role, item_raw in inputs_raw.items():
        item = require_mapping(item_raw, f"binding.inputs.{role}")
        _keys(
            item,
            {"registered_dataset", "fields"},
            f"binding.inputs.{role}",
            required={"registered_dataset"},
        )
        fields_raw = require_mapping(item.get("fields", {}), f"binding.inputs.{role}.fields")
        fields = {
            require_string(name, f"binding.inputs.{role}.fields key"): require_string(
                source, f"binding.inputs.{role}.fields.{name}"
            )
            for name, source in fields_raw.items()
        }
        inputs.append(
            StrategyBindingInput(
                role=role,
                registered_dataset=require_string(
                    item.get("registered_dataset"),
                    f"binding.inputs.{role}.registered_dataset",
                ),
                fields=MappingProxyType(fields),
            )
        )
    return StrategyBinding(
        binding_id=require_string(value.get("id"), "binding.id"),
        strategy_id=require_string(strategy.get("id"), "binding.strategy.id"),
        strategy_version=require_string(strategy.get("version"), "binding.strategy.version"),
        inputs=tuple(inputs),
        source_path=path,
        fingerprint=digest_document(raw),
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
            "manifest": _manifest_dict(manifest),
            "binding": _binding_dict(binding) if binding is not None else None,
            "registered_field_inventory": inventory,
            "effective_config_id": _effective_config_id(catalog, manifest, binding),
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


@dataclass(frozen=True, slots=True)
class StrategyInputResolver:
    project: Project
    manifest: StrategyManifest
    binding: StrategyBinding
    loader: ConfigDrivenDataLoader
    effective_config_id: str

    @classmethod
    def from_project(
        cls,
        project: Project,
        manifest: StrategyManifest,
        binding: StrategyBinding,
    ) -> StrategyInputResolver:
        plan = require_strategy_binding(project, manifest, binding)
        return cls(
            project,
            manifest,
            binding,
            ConfigDrivenDataLoader.from_project(project),
            str(plan.parameters["effective_config_id"]),
        )

    def resolve(
        self,
        decision_time: str | pd.Timestamp,
        *,
        tickers: tuple[str, ...] | None = None,
    ) -> ResolvedStrategyInputs:
        return _resolve_inputs(
            self.loader,
            self.manifest,
            self.binding,
            pd.Timestamp(decision_time),
            tickers,
            self.effective_config_id,
        )


def resolve_strategy_inputs(
    project: Project,
    manifest: StrategyManifest,
    binding: StrategyBinding,
    *,
    decision_time: str | pd.Timestamp,
    tickers: tuple[str, ...] | None = None,
) -> ResolvedStrategyInputs:
    return StrategyInputResolver.from_project(project, manifest, binding).resolve(
        decision_time,
        tickers=tickers,
    )


def load_strategy_callable(
    project: Project,
    manifest: StrategyManifest,
) -> Callable[..., pd.DataFrame | pd.Series]:
    source = project.contained(project.paths.extensions / manifest.implementation.source)
    if not source.is_relative_to(project.paths.extensions):
        raise QlibxError(
            "QLIBX_STRATEGY_SOURCE_OUTSIDE_EXTENSIONS",
            f"Strategy source is outside the extension root: {source}",
            action="Keep trusted Strategy code below the configured extension root.",
        )
    if not source.is_file():
        raise QlibxError(
            "QLIBX_STRATEGY_SOURCE_MISSING",
            f"Strategy source does not exist: {source}",
            action="Create the manifest-declared trusted Strategy source.",
        )
    module_name = f"qlibx_project_strategy_{digest_file(source)[:16]}"
    spec = spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise QlibxError(
            "QLIBX_STRATEGY_SOURCE_INVALID",
            f"Cannot load Strategy source: {source}",
            action="Use an importable Python source file.",
        )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    program = getattr(module, manifest.implementation.callable, None)
    if not callable(program):
        raise QlibxError(
            "QLIBX_STRATEGY_CALLABLE_MISSING",
            f"Strategy callable is missing: {manifest.implementation.callable!r}",
            action="Export the callable declared by the Strategy manifest.",
        )
    return program


def invoke_pandas_strategy(
    manifest: StrategyManifest,
    resolved: ResolvedStrategyInputs,
    program: Callable[..., Any],
) -> pd.DataFrame | pd.Series:
    if (manifest.strategy_id, manifest.version) != (
        resolved.strategy_id,
        resolved.strategy_version,
    ):
        raise QlibxError(
            "QLIBX_STRATEGY_RESOLUTION_MISMATCH",
            "Resolved inputs belong to another Strategy manifest",
            action="Resolve inputs again with the selected manifest and binding.",
        )
    kwargs: dict[str, Any] = {
        name: frame.copy(deep=True) for name, frame in resolved.inputs.items()
    }
    overlap = sorted(set(kwargs) & set(manifest.parameters))
    if overlap:
        raise QlibxError(
            "QLIBX_STRATEGY_PARAMETER_COLLISION",
            f"Strategy parameters collide with input roles: {overlap}",
            action="Rename the parameters or canonical input roles.",
        )
    kwargs.update(dict(manifest.parameters))
    try:
        inspect.signature(program).bind(**kwargs)
    except TypeError as error:
        raise QlibxError(
            "QLIBX_STRATEGY_SIGNATURE_MISMATCH",
            f"Strategy callable does not match its manifest: {error}",
            action="Match callable keywords to inputs and parameters.",
        ) from error
    before = digest_dataset(kwargs)
    result = program(**kwargs)
    if digest_dataset(kwargs) != before:
        raise QlibxError(
            "QLIBX_STRATEGY_INPUT_MUTATED",
            "Strategy mutated its bounded pandas inputs",
            action="Return a new pandas object instead of mutating inputs.",
        )
    if not isinstance(result, (pd.DataFrame, pd.Series)):
        raise QlibxError(
            "QLIBX_STRATEGY_OUTPUT_NOT_PANDAS",
            f"Strategy returned {type(result).__name__}, not a pandas object",
            action="Return a pandas Series or DataFrame.",
        )
    return result.copy(deep=True)


def pandas_decision_program(
    resolver: StrategyInputResolver,
    program: Callable[..., Any],
) -> Callable[..., Any]:
    """Adapt one plain pandas callable to the existing Qlib decision callback."""
    from qlibx.strategy import DecisionResult

    def decide(context: Any, _parameters: Mapping[str, Any]) -> DecisionResult:
        tickers = tuple(map(str, context.datasets["universe"].columns))
        resolved = resolver.resolve(context.decision_time, tickers=tickers)
        _match_execution_universe(
            context.datasets["universe"],
            resolved.inputs["universe"],
            context.decision_time,
        )
        payload = invoke_pandas_strategy(resolver.manifest, resolved, program)
        if isinstance(payload, pd.DataFrame) and len(payload) > 1:
            payload = payload.tail(1)
        return DecisionResult(
            resolver.manifest.output_kind,
            payload,
            diagnostics={
                "binding_id": resolver.binding.binding_id,
                "effective_config_id": resolver.effective_config_id,
            },
        )

    return decide


def run_manifest_strategy_execution(
    project: Project,
    manifest: StrategyManifest,
    binding: StrategyBinding,
    **execution_inputs: Any,
) -> Any:
    """Run a bound plain-pandas weight Strategy inside Qlib's decision loop."""
    from qlibx.execution import run_strategy_execution
    from qlibx.strategy import StrategyDefinition

    if manifest.output_kind != "weight":
        raise QlibxError(
            "QLIBX_STRATEGY_EXECUTION_OUTPUT_INVALID",
            f"Qlib execution requires weight output, not {manifest.output_kind!r}",
            action="Add an explicit signal-to-weight Strategy or transform before execution.",
        )
    resolver = StrategyInputResolver.from_project(project, manifest, binding)
    program = load_strategy_callable(project, manifest)
    definition = StrategyDefinition(
        manifest.strategy_id,
        manifest.name,
        {},
        (),
        "weight",
        version=manifest.version,
    )
    return run_strategy_execution(
        definition,
        pandas_decision_program(resolver, program),
        datasets={},
        effective_config_id=resolver.effective_config_id,
        **execution_inputs,
    )


def _strategy_input(role: str, raw: Any) -> StrategyInput:
    value = require_mapping(raw, f"inputs.{role}")
    _keys(value, {"meaning", "pandas", "fields"}, f"inputs.{role}")
    pandas_raw = require_mapping(value.get("pandas"), f"inputs.{role}.pandas")
    _keys(
        pandas_raw,
        {"kind", "index", "dtype"},
        f"inputs.{role}.pandas",
        required={"kind", "index"},
    )
    kind = require_string(pandas_raw.get("kind"), f"inputs.{role}.pandas.kind")
    if kind not in {"table", "matrix"}:
        raise QlibxError(
            "QLIBX_STRATEGY_PANDAS_KIND_INVALID",
            f"Unsupported pandas kind for {role!r}: {kind!r}",
            action="Use table or matrix.",
        )
    index_raw = pandas_raw.get("index")
    if not isinstance(index_raw, list) or not index_raw:
        raise QlibxError(
            "QLIBX_STRATEGY_INDEX_INVALID",
            f"inputs.{role}.pandas.index must be a non-empty list",
            action="Declare canonical index field names in order.",
        )
    index = tuple(require_string(item, f"inputs.{role}.pandas.index[]") for item in index_raw)
    fields_raw = require_mapping(value.get("fields", {}), f"inputs.{role}.fields")
    fields: list[StrategyField] = []
    for name, field_raw in fields_raw.items():
        field_value = require_mapping(field_raw, f"inputs.{role}.fields.{name}")
        _keys(
            field_value,
            {"meaning", "dtype", "unit", "nullable"},
            f"inputs.{role}.fields.{name}",
        )
        nullable = field_value.get("nullable")
        if not isinstance(nullable, bool):
            raise QlibxError(
                "QLIBX_STRATEGY_FIELD_NULLABLE_INVALID",
                f"inputs.{role}.fields.{name}.nullable must be boolean",
                action="Declare nullable as true or false.",
            )
        fields.append(
            StrategyField(
                name=name,
                meaning=require_string(field_value.get("meaning"), f"{name}.meaning"),
                dtype=require_string(field_value.get("dtype"), f"{name}.dtype"),
                unit=require_string(field_value.get("unit"), f"{name}.unit"),
                nullable=nullable,
            )
        )
    if kind == "table" and not fields:
        raise QlibxError(
            "QLIBX_STRATEGY_FIELDS_EMPTY",
            f"Table input {role!r} must declare canonical fields",
            action="Declare every pandas column the Strategy reads.",
        )
    return StrategyInput(
        role=role,
        meaning=require_string(value.get("meaning"), f"inputs.{role}.meaning"),
        pandas=PandasInputContract(
            kind=kind,
            index=index,
            dtype=(
                require_string(pandas_raw.get("dtype"), f"inputs.{role}.pandas.dtype")
                if pandas_raw.get("dtype") is not None
                else None
            ),
        ),
        fields=tuple(fields),
    )


def _input_requirement(
    manifest: StrategyManifest,
    item: StrategyInput,
) -> CapabilityRequirement:
    fields = tuple(field.name for field in item.fields)
    return CapabilityRequirement(
        requirement_id=f"input.{item.role}",
        role=item.role,
        meaning=item.meaning,
        axis=" x ".join(item.pandas.index),
        unit=", ".join(dict.fromkeys(field.unit for field in item.fields)) or "membership",
        currency="not_applicable",
        purpose=f"Supply bounded pandas input {item.role!r} to {manifest.strategy_id!r}.",
        satisfaction_rule=(
            "A project binding names a registered logical dataset and maps every canonical field."
        ),
        availability="Every observation must be available at or before the decision time.",
        mandatory=True,
        unavailable_effect=f"Strategy input {item.role!r} cannot be constructed.",
        alternatives=(
            DerivationAlternative(
                alternative_id="registered_binding",
                description="Use an explicit binding to a registered logical dataset.",
                required_inputs=(item.role, *fields),
                derivation="registered logical dataset projection",
            ),
        ),
        next_commands=(
            "qlibx strategy plan "
            f"--strategy {manifest.strategy_id} --binding <binding> --root <project>",
        ),
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
    required = {field.name for field in contract.fields}
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


def _resolve_inputs(
    loader: ConfigDrivenDataLoader,
    manifest: StrategyManifest,
    binding: StrategyBinding,
    cutoff: pd.Timestamp,
    tickers: tuple[str, ...] | None,
    effective_config_id: str,
) -> ResolvedStrategyInputs:
    by_role = binding.by_role()
    resolved: dict[str, pd.DataFrame] = {}
    for contract in manifest.all_inputs:
        selected = by_role[contract.role]
        if contract.pandas.kind == "matrix":
            frame = (
                _load_universe_matrix(
                    loader,
                    selected.registered_dataset,
                    cutoff=cutoff,
                    tickers=tickers,
                )
                if contract.role == "universe"
                else loader.load_matrix(
                    selected.registered_dataset,
                    tickers=tickers,
                    as_of=cutoff,
                )
            )
            frame = _tail_periods(frame, manifest.lookback_rows)
            if contract.pandas.dtype is not None:
                try:
                    frame = frame.astype(contract.pandas.dtype)
                except (TypeError, ValueError) as error:
                    raise QlibxError(
                        "QLIBX_STRATEGY_INPUT_DTYPE_INVALID",
                        f"Input {contract.role!r} cannot convert to {contract.pandas.dtype}",
                        action="Correct the manifest or bind a compatible registered dataset.",
                    ) from error
            _validate_matrix_cells(contract, frame)
        else:
            frame = loader.load_table(
                selected.registered_dataset,
                tickers=tickers,
                as_of=cutoff,
            )
            source_fields = dict(selected.fields)
            selected_columns = [*contract.pandas.index, *source_fields.values()]
            missing = sorted(set(selected_columns) - set(frame.columns))
            if missing:
                raise QlibxError(
                    "QLIBX_STRATEGY_BOUND_FIELDS_MISSING",
                    f"Bound input {contract.role!r} is missing fields: {missing}",
                    action="Correct the binding after inspecting registered fields.",
                )
            frame = frame.loc[:, selected_columns].rename(
                columns={source: canonical for canonical, source in source_fields.items()}
            )
            frame = frame.set_index(list(contract.pandas.index)).sort_index()
            frame = _tail_periods(frame, manifest.lookback_rows)
            _validate_fields(contract, frame)
        resolved[contract.role] = frame.copy(deep=True)
    _validate_universe_alignment(manifest, resolved)
    return ResolvedStrategyInputs(
        strategy_id=manifest.strategy_id,
        strategy_version=manifest.version,
        binding_id=binding.binding_id,
        decision_time=cutoff,
        inputs=MappingProxyType(resolved),
        effective_config_id=effective_config_id,
    )


def _load_universe_matrix(
    loader: ConfigDrivenDataLoader,
    dataset_name: str,
    *,
    cutoff: pd.Timestamp,
    tickers: tuple[str, ...] | None,
) -> pd.DataFrame:
    axes = require_matrix_axes(loader.catalog.datasets[dataset_name])
    table = loader.load_table(dataset_name, as_of=cutoff, tickers=tickers)
    duplicate = table.duplicated([axes.index, axes.columns], keep=False)
    if duplicate.any():
        raise QlibxError(
            "QLIBX_STRATEGY_UNIVERSE_DUPLICATE",
            f"Universe has {int(duplicate.sum())} duplicate date/ticker rows",
            action="Correct the registered universe query before Strategy execution.",
        )
    matrix = table.pivot(index=axes.index, columns=axes.columns, values=axes.values)
    matrix = matrix.sort_index().sort_index(axis=1)
    if matrix.isna().any().any():
        raise QlibxError(
            "QLIBX_STRATEGY_UNIVERSE_NULL",
            "Universe membership is missing for one or more registered date/ticker cells",
            action="Provide explicit true/false membership; do not infer membership from absence.",
        )
    return matrix.astype(bool)


def _validate_fields(contract: StrategyInput, frame: pd.DataFrame) -> None:
    for declared_field in contract.fields:
        try:
            converted = frame[declared_field.name].astype(declared_field.dtype)
        except (TypeError, ValueError) as error:
            raise QlibxError(
                "QLIBX_STRATEGY_INPUT_DTYPE_INVALID",
                f"Field {contract.role}.{declared_field.name} "
                f"cannot convert to {declared_field.dtype}",
                action="Correct the binding or manifest dtype.",
            ) from error
        if not declared_field.nullable and converted.isna().any():
            raise QlibxError(
                "QLIBX_STRATEGY_INPUT_NULL_INVALID",
                f"Field {contract.role}.{declared_field.name} contains null values",
                action="Bind a complete field or declare nullable behavior.",
            )
        frame[declared_field.name] = converted


def _validate_matrix_cells(contract: StrategyInput, frame: pd.DataFrame) -> None:
    """Apply a matrix input's declared nullability to its cells.

    A matrix spreads one semantic field across ticker columns, so the manifest's field
    declaration constrains every cell rather than a named column. Without this the
    `nullable: false` a manifest declares would only ever bind on table inputs.
    """
    for declared_field in contract.fields:
        if declared_field.nullable or not frame.isna().to_numpy().any():
            continue
        raise QlibxError(
            "QLIBX_STRATEGY_INPUT_NULL_INVALID",
            f"Field {contract.role}.{declared_field.name} contains null values",
            action="Bind a complete matrix or declare nullable behavior.",
            context={"role": contract.role, "field": declared_field.name},
        )


def _validate_universe_alignment(
    manifest: StrategyManifest,
    inputs: Mapping[str, pd.DataFrame],
) -> None:
    """Reject any bound input carrying a ticker the inherited universe does not declare.

    The ticker axis comes from the manifest's declared pandas kind, never from the shape
    of the data: inferring it from the frame made the check vacuous, because "the columns
    all sit inside the universe" is false in exactly the case worth reporting.
    """
    universe_tickers = set(map(str, inputs["universe"].columns))
    for contract in manifest.all_inputs:
        role = contract.role
        if role == "universe":
            continue
        frame = inputs[role]
        if contract.pandas.kind == "matrix":
            tickers = set(map(str, frame.columns))
        else:
            ticker_level = _ticker_index_level(contract)
            if ticker_level is None:
                continue
            tickers = set(map(str, frame.index.get_level_values(ticker_level)))
        outside = sorted(tickers - universe_tickers)
        if outside:
            raise QlibxError(
                "QLIBX_STRATEGY_UNIVERSE_MISMATCH",
                f"Input {role!r} contains tickers outside universe axes: {outside}",
                action="Align bound datasets with the inherited universe input.",
                context={"role": role, "outside_universe": outside},
            )


def _ticker_index_level(contract: StrategyInput) -> int | None:
    """Locate the declared ticker level of a table input, or None when it has none."""
    for level, name in enumerate(contract.pandas.index):
        if name == "ticker":
            return level
    return None


def _match_execution_universe(
    execution: pd.DataFrame,
    registered: pd.DataFrame,
    decision_time: pd.Timestamp,
) -> None:
    if decision_time not in execution.index or decision_time not in registered.index:
        raise QlibxError(
            "QLIBX_STRATEGY_EXECUTION_UNIVERSE_MISMATCH",
            "Registered and execution universe do not both contain the decision time",
            action="Bind the same point-in-time universe used by the execution profile.",
        )
    actual = registered.loc[decision_time].reindex(execution.columns).astype(bool)
    expected = execution.loc[decision_time].astype(bool)
    try:
        pd.testing.assert_series_equal(actual, expected, check_names=False)
    except AssertionError as error:
        raise QlibxError(
            "QLIBX_STRATEGY_EXECUTION_UNIVERSE_MISMATCH",
            "Registered Strategy universe differs from the Qlib execution universe",
            action="Bind the same point-in-time universe used by the execution profile.",
        ) from error


def _tail_periods(frame: pd.DataFrame, rows: int) -> pd.DataFrame:
    index = (
        frame.index.get_level_values(0) if isinstance(frame.index, pd.MultiIndex) else frame.index
    )
    periods = pd.Index(index).drop_duplicates().sort_values()
    if len(periods) <= rows:
        return frame.copy(deep=True)
    return frame.loc[pd.Index(index).isin(set(periods[-rows:]))].copy(deep=True)


def _config_path(project: Project, value: str | Path, directory: str) -> Path:
    supplied = Path(value)
    if supplied.suffix.lower() not in {".yaml", ".yml"}:
        supplied = Path(f"{supplied}.yaml")
    path = project.contained(
        supplied if supplied.is_absolute() else project.paths.config / directory / supplied
    )
    expected = (project.paths.config / directory).resolve()
    if not path.is_relative_to(expected):
        raise QlibxError(
            "QLIBX_STRATEGY_CONFIG_OUTSIDE_ROOT",
            f"Strategy {directory} config is outside {expected}: {path}",
            action=f"Keep Strategy {directory} YAML below the project config root.",
        )
    return path


def _schema(raw: Mapping[str, Any], path: Path) -> None:
    if raw.get("schema_version") != 1:
        raise QlibxError(
            "QLIBX_STRATEGY_CONFIG_SCHEMA_UNSUPPORTED",
            f"Strategy config schema_version must be 1: {path}",
            action="Use the installed Strategy schema version.",
        )


def _keys(
    value: Mapping[str, Any],
    allowed: set[str],
    field: str,
    *,
    required: set[str] | None = None,
) -> None:
    missing = sorted((allowed if required is None else required) - set(value))
    unknown = sorted(set(value) - allowed)
    if missing or unknown:
        raise QlibxError(
            "QLIBX_STRATEGY_CONFIG_KEYS_INVALID",
            f"Invalid keys in {field}; missing={missing}, unknown={unknown}",
            action="Match the installed Strategy manifest or binding schema exactly.",
        )


def _input_dict(item: StrategyInput) -> dict[str, Any]:
    return {
        "role": item.role,
        "meaning": item.meaning,
        "pandas": asdict(item.pandas),
        "fields": [asdict(field) for field in item.fields],
        "inherited": item.inherited,
    }


def _manifest_dict(manifest: StrategyManifest) -> dict[str, Any]:
    return {
        "strategy": {
            "id": manifest.strategy_id,
            "version": manifest.version,
            "name": manifest.name,
        },
        "contract": manifest.contract,
        "implementation": asdict(manifest.implementation),
        "lookback": {"kind": "rows", "value": manifest.lookback_rows},
        "inputs": [_input_dict(item) for item in manifest.all_inputs],
        "output": {"kind": manifest.output_kind},
        "fingerprint": manifest.fingerprint,
    }


def _binding_dict(binding: StrategyBinding) -> dict[str, Any]:
    return {
        "id": binding.binding_id,
        "strategy": {"id": binding.strategy_id, "version": binding.strategy_version},
        "inputs": {
            item.role: {
                "registered_dataset": item.registered_dataset,
                "fields": dict(item.fields),
            }
            for item in binding.inputs
        },
        "fingerprint": binding.fingerprint,
    }


def _effective_config_id(
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


__all__ = [
    "PandasInputContract",
    "ResolvedStrategyInputs",
    "StrategyBinding",
    "StrategyBindingInput",
    "StrategyField",
    "StrategyImplementation",
    "StrategyInput",
    "StrategyInputResolver",
    "StrategyManifest",
    "base_universe_input",
    "invoke_pandas_strategy",
    "load_strategy_binding",
    "load_strategy_callable",
    "load_strategy_manifest",
    "pandas_decision_program",
    "plan_strategy_binding",
    "require_strategy_binding",
    "resolve_strategy_inputs",
    "run_manifest_strategy_execution",
]
