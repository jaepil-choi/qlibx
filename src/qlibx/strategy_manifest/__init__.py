"""Project-owned Strategy manifests, bindings, and pandas input resolution.

A Strategy reaches its data through four steps, and each one is a separate question:
what does the manifest declare, can this project satisfy it, what exactly may the
Strategy read, and what happens when it runs. Keeping them in separate files is what
lets the capability half be reworked without touching the resolution half.

Layout::

    contracts.py    value objects, and the requirements a manifest declares
    loading.py      manifest and binding YAML to contracts
    capability.py   evidence against a project, and the read-only plan
    resolution.py   approved binding to bounded pandas inputs
    invocation.py   trusted callable loading, invocation, Qlib execution adapter

This package re-exports the whole public surface, so ``from qlibx.strategy_manifest import
X`` keeps working regardless of which file ``X`` lives in.
"""

from __future__ import annotations

from .capability import plan_strategy_binding, require_strategy_binding
from .contracts import (
    PandasInputContract,
    ResolvedStrategyInputs,
    StrategyBinding,
    StrategyBindingInput,
    StrategyField,
    StrategyImplementation,
    StrategyInput,
    StrategyManifest,
    base_universe_input,
)
from .invocation import (
    invoke_pandas_strategy,
    load_strategy_callable,
    pandas_decision_program,
    run_manifest_strategy_execution,
)
from .loading import load_strategy_binding, load_strategy_manifest
from .resolution import StrategyInputResolver, resolve_strategy_inputs

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
