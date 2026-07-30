"""Load the project-local Strategy callable and run it under the decision contract.

Loading executes trusted project-owned code, so the checks here are containment and
contract-matching, not a security sandbox: the extension root bounds where code may live,
and the manifest bounds what the callable may be handed and what it may return.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from importlib.util import module_from_spec, spec_from_file_location
from typing import Any

import pandas as pd

from qlibx.errors import QlibxError
from qlibx.project import Project
from qlibx.serialization import digest_dataset, digest_file

from .contracts import ResolvedStrategyInputs, StrategyBinding, StrategyManifest
from .resolution import StrategyInputResolver


def load_strategy_callable(
    project: Project,
    manifest: StrategyManifest,
) -> Callable[..., pd.DataFrame | pd.Series]:
    source = project.contained(project.paths.extensions / manifest.implementation.source)
    if not source.is_relative_to(project.paths.extensions):
        raise QlibxError(
            "QLIBX_BOUNDARY_EXTENSION_PATH",
            f"Strategy source is outside the extension root: {source}",
            action="Keep trusted Strategy code below the configured extension root.",
        )
    if not source.is_file():
        raise QlibxError(
            "QLIBX_NOT_FOUND_STRATEGY_SOURCE",
            f"Strategy source does not exist: {source}",
            action="Create the manifest-declared trusted Strategy source.",
        )
    module_name = f"qlibx_project_strategy_{digest_file(source)[:16]}"
    spec = spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise QlibxError(
            "QLIBX_INVALID_STRATEGY_SOURCE",
            f"Cannot load Strategy source: {source}",
            action="Use an importable Python source file.",
        )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    program = getattr(module, manifest.implementation.callable, None)
    if not callable(program):
        raise QlibxError(
            "QLIBX_NOT_FOUND_STRATEGY_CALLABLE",
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
            "QLIBX_INVALID_RESOLVED_INPUTS",
            "Resolved inputs belong to another Strategy manifest",
            action="Resolve inputs again with the selected manifest and binding.",
        )
    kwargs: dict[str, Any] = {
        name: frame.copy(deep=True) for name, frame in resolved.inputs.items()
    }
    overlap = sorted(set(kwargs) & set(manifest.parameters))
    if overlap:
        raise QlibxError(
            "QLIBX_INVALID_PARAMETER_COLLISION",
            f"Strategy parameters collide with input roles: {overlap}",
            action="Rename the parameters or canonical input roles.",
        )
    kwargs.update(dict(manifest.parameters))
    try:
        inspect.signature(program).bind(**kwargs)
    except TypeError as error:
        raise QlibxError(
            "QLIBX_INVALID_CALLABLE_SIGNATURE",
            f"Strategy callable does not match its manifest: {error}",
            action="Match callable keywords to inputs and parameters.",
        ) from error
    before = digest_dataset(kwargs)
    result = program(**kwargs)
    if digest_dataset(kwargs) != before:
        raise QlibxError(
            "QLIBX_BOUNDARY_INPUT_MUTATED",
            "Strategy mutated its bounded pandas inputs",
            action="Return a new pandas object instead of mutating inputs.",
        )
    if not isinstance(result, (pd.DataFrame, pd.Series)):
        raise QlibxError(
            "QLIBX_INVALID_OUTPUT_TYPE",
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
            "QLIBX_INVALID_EXECUTION_OUTPUT_KIND",
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


def _match_execution_universe(
    execution: pd.DataFrame,
    registered: pd.DataFrame,
    decision_time: pd.Timestamp,
) -> None:
    if decision_time not in execution.index or decision_time not in registered.index:
        raise QlibxError(
            "QLIBX_BOUNDARY_EXECUTION_UNIVERSE",
            "Registered and execution universe do not both contain the decision time",
            action="Bind the same point-in-time universe used by the execution profile.",
        )
    actual = registered.loc[decision_time].reindex(execution.columns).astype(bool)
    expected = execution.loc[decision_time].astype(bool)
    try:
        pd.testing.assert_series_equal(actual, expected, check_names=False)
    except AssertionError as error:
        raise QlibxError(
            "QLIBX_BOUNDARY_EXECUTION_UNIVERSE",
            "Registered Strategy universe differs from the Qlib execution universe",
            action="Bind the same point-in-time universe used by the execution profile.",
        ) from error


__all__ = [
    "invoke_pandas_strategy",
    "load_strategy_callable",
    "pandas_decision_program",
    "run_manifest_strategy_execution",
]
