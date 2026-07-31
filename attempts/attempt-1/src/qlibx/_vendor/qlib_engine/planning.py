from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ConfigurationError, ProjectConfig, backtest_dataset_names
from .data import MatrixCatalog
from .hashing import callable_fingerprint, deterministic_run_id, file_hash, stable_hash
from .models import RunRecord


@dataclass(frozen=True)
class RunPlan:
    strategy_id: str
    alpha_run_id: str
    backtest_run_id: str
    config_fingerprint: str
    alpha_dataset_fingerprint: str
    backtest_dataset_fingerprint: str
    strategy_fingerprint: str
    execution_fingerprint: str


def build_plan(project: ProjectConfig, strategy_id: str) -> RunPlan:
    data = MatrixCatalog(project)
    strategy = project.strategies[strategy_id]
    strategy_fingerprint = callable_fingerprint(load_callable(strategy.callable_path))
    alpha_dataset_fingerprint = data.fingerprint(strategy.datasets.values())
    config_fingerprint = stable_hash(
        {
            "strategy_id": strategy_id,
            "callable": strategy.callable_path,
            "datasets": strategy.datasets,
            "parameters": strategy.parameters,
        }
    )
    alpha_run_id = deterministic_run_id(
        "alpha",
        {
            "config": config_fingerprint,
            "data": alpha_dataset_fingerprint,
            "strategy": strategy_fingerprint,
        },
    )
    backtest_dataset_fingerprint = data.fingerprint(backtest_dataset_names(project.backtest))
    execution_fingerprint = execution_fingerprint_for_runtime()
    backtest_run_id = deterministic_run_id(
        "backtest",
        {
            "alpha_run_id": alpha_run_id,
            "config": project.backtest.identity_payload(),
            "data": backtest_dataset_fingerprint,
            "execution": execution_fingerprint,
        },
    )
    return RunPlan(
        strategy_id=strategy_id,
        alpha_run_id=alpha_run_id,
        backtest_run_id=backtest_run_id,
        config_fingerprint=config_fingerprint,
        alpha_dataset_fingerprint=alpha_dataset_fingerprint,
        backtest_dataset_fingerprint=backtest_dataset_fingerprint,
        strategy_fingerprint=strategy_fingerprint,
        execution_fingerprint=execution_fingerprint,
    )


def alpha_record(project: ProjectConfig, plan: RunPlan) -> RunRecord:
    strategy = project.strategies[plan.strategy_id]
    return RunRecord(
        run_id=plan.alpha_run_id,
        run_kind="alpha",
        strategy_id=plan.strategy_id,
        status="complete",
        config_fingerprint=plan.config_fingerprint,
        dataset_fingerprint=plan.alpha_dataset_fingerprint,
        strategy_fingerprint=plan.strategy_fingerprint,
        metadata={
            "callable": strategy.callable_path,
            "datasets": dict(strategy.datasets),
            "parameters": dict(strategy.parameters),
        },
    )


def backtest_record(
    project: ProjectConfig,
    plan: RunPlan,
    backend_metadata: Mapping[str, Any],
) -> RunRecord:
    return RunRecord(
        run_id=plan.backtest_run_id,
        run_kind="backtest",
        strategy_id=plan.strategy_id,
        status="complete",
        config_fingerprint=stable_hash(project.backtest.identity_payload()),
        dataset_fingerprint=plan.backtest_dataset_fingerprint,
        strategy_fingerprint=plan.execution_fingerprint,
        metadata={
            "backtest_config": asdict(project.backtest),
            "context_fingerprint": stable_hash(
                {
                    "config": project.backtest.identity_payload(),
                    "data": plan.backtest_dataset_fingerprint,
                }
            ),
            "execution_fingerprint": plan.execution_fingerprint,
            **backend_metadata,
        },
    )


def load_callable(path: str) -> Callable[..., pd.DataFrame]:
    if ":" not in path:
        raise ConfigurationError(f"strategy callable must use module:attribute syntax: {path}")
    module_name, attribute_path = path.split(":", 1)
    value: Any = importlib.import_module(module_name)
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute)
    if not callable(value):
        raise ConfigurationError(f"strategy target is not callable: {path}")
    return value


def execution_fingerprint_for_runtime() -> str:
    paths = []
    for module_name in (
        "qlibx._vendor.qlib_engine.execution",
        "qlibx._vendor.qlib_engine.portfolio",
        "qlibx._vendor.qlib_backend.backend",
        "qlibx._vendor.qlib_backend.exchange",
    ):
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"cannot fingerprint execution module: {module_name}")
        paths.append((module_name, file_hash(Path(spec.origin))))
    return stable_hash(paths)
