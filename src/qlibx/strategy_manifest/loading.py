"""Read project-owned Strategy manifest and binding YAML into contracts.

Every check here is structural: keys, types, and declared vocabulary. Whether a binding can
actually be satisfied by registered data is evidence, not schema, and lives in
:mod:`qlibx.strategy_manifest.capability`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from qlibx.config import read_yaml, require_mapping, require_string
from qlibx.errors import QlibxError
from qlibx.project import Project
from qlibx.serialization import digest_document

from .contracts import (
    PandasInputContract,
    StrategyBinding,
    StrategyBindingInput,
    StrategyField,
    StrategyImplementation,
    StrategyInput,
    StrategyManifest,
)


def load_strategy_manifest(project: Project, strategy: str | Path) -> StrategyManifest:
    path = _config_path(project, strategy, "strategies")
    raw = read_yaml(path)
    _keys(raw, {"schema_version", "contract", "strategy"}, str(path))
    _schema(raw, path)
    contract = require_string(raw.get("contract"), "contract")
    if contract != "qlibx.pandas_strategy":
        raise QlibxError(
            "UNSUPPORTED",
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
            "INVALID",
            "Strategy lookback.kind must be rows",
            action="Use a fixed positive row lookback.",
        )
    rows = lookback.get("value")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
        raise QlibxError(
            "INVALID",
            "Strategy lookback.value must be a positive integer",
            action="Declare the fixed number of rows supplied at every decision.",
        )
    inputs_raw = require_mapping(value.get("inputs"), "inputs")
    if "universe" in inputs_raw:
        raise QlibxError(
            "INVALID",
            "universe is inherited from qlibx.pandas_strategy",
            action="Remove universe from the manifest and bind it in the binding YAML.",
        )
    inputs = tuple(_strategy_input(role, item) for role, item in inputs_raw.items())
    if not inputs:
        raise QlibxError(
            "MISSING",
            "Strategy must declare at least one Strategy-specific pandas input",
            action="Declare the canonical pandas data used by the Strategy.",
        )
    output = require_mapping(value.get("output"), "output")
    _keys(output, {"kind"}, "output")
    output_kind = require_string(output.get("kind"), "output.kind")
    if output_kind not in {"signal", "weight", "order", "payload"}:
        raise QlibxError(
            "INVALID",
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
            "INVALID",
            f"Unsupported pandas kind for {role!r}: {kind!r}",
            action="Use table or matrix.",
        )
    index_raw = pandas_raw.get("index")
    if not isinstance(index_raw, list) or not index_raw:
        raise QlibxError(
            "INVALID",
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
                "INVALID",
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
            "MISSING",
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
            "BOUNDARY",
            f"Strategy {directory} config is outside {expected}: {path}",
            action=f"Keep Strategy {directory} YAML below the project config root.",
        )
    return path


def _schema(raw: Mapping[str, Any], path: Path) -> None:
    if raw.get("schema_version") != 1:
        raise QlibxError(
            "UNSUPPORTED",
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
            "INVALID",
            f"Invalid keys in {field}; missing={missing}, unknown={unknown}",
            action="Match the installed Strategy manifest or binding schema exactly.",
        )


__all__ = ["load_strategy_binding", "load_strategy_manifest"]
