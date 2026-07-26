from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pandas as pd
import pytest
import yaml


PUBLIC_MODULE = "qlib_extended"
PUBLIC_SYMBOLS = {
    "ConfigurationError",
    "build_ensemble",
    "create_report",
    "open_run_catalog",
    "run_strategy_batch",
}


@dataclass(frozen=True)
class WorkflowProject:
    config_path: Path
    catalog_path: Path
    artifact_dir: Path
    audit_path: Path
    returns: pd.DataFrame


def load_public_api() -> ModuleType:
    """Load only the proposed production facade, with an actionable red failure."""

    try:
        module = importlib.import_module(PUBLIC_MODULE)
    except ModuleNotFoundError:
        pytest.fail(
            "Goal 11-15 are intentionally red: implement the public 'qlib_extended' "
            "package before adding adapters to the tests."
        )
    missing = sorted(PUBLIC_SYMBOLS.difference(vars(module)))
    assert not missing, f"public kwam_qlib API is incomplete: {missing}"
    return module


def make_project(
    root: Path,
    *,
    strategies: Mapping[str, Mapping[str, Any]] | None = None,
) -> WorkflowProject:
    dates = pd.bdate_range("2024-01-02", periods=4)
    returns = pd.DataFrame(
        [[0.01, -0.01], [0.02, 0.00], [-0.01, 0.03], [0.00, 0.01]],
        index=dates,
        columns=["A", "B"],
    ).rename_axis(index="date", columns="ticker")
    universe = pd.DataFrame(True, index=dates, columns=returns.columns).rename_axis(
        index="date", columns="ticker"
    )
    benchmark_weight = pd.DataFrame(
        0.5, index=dates, columns=returns.columns
    ).rename_axis(index="date", columns="ticker")
    execution_price = (100.0 * (1.0 + returns).cumprod()).rename_axis(
        index="date", columns="ticker"
    )
    position_unit_factor = pd.DataFrame(
        1.0, index=dates, columns=returns.columns
    ).rename_axis(index="date", columns="ticker")

    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_matrix(data_dir / "returns.parquet", returns, "return")
    _write_matrix(data_dir / "universe.parquet", universe, "in_universe")
    _write_matrix(
        data_dir / "benchmark_weight.parquet",
        benchmark_weight,
        "benchmark_weight",
    )
    _write_matrix(
        data_dir / "execution_price.parquet", execution_price, "execution_price"
    )
    _write_matrix(
        data_dir / "position_unit_factor.parquet",
        position_unit_factor,
        "position_unit_factor",
    )

    catalog_path = root / "runs.duckdb"
    artifact_dir = root / "artifacts"
    audit_path = root / "strategy-invocations.txt"
    configured_strategies = strategies or {
        "alpha_a": strategy_config(scale=1.0, audit_path=audit_path),
        "alpha_b": strategy_config(scale=-0.5, audit_path=audit_path),
    }
    config = {
        "version": 1,
        "run_store": {
            "catalog_uri": str(catalog_path),
            "artifact_dir": str(artifact_dir),
        },
        "data": {
            "datasets": {
                "returns": {
                    "path": str(data_dir / "returns.parquet"),
                    "format": "parquet",
                    "value_column": "return",
                },
                "universe": {
                    "path": str(data_dir / "universe.parquet"),
                    "format": "parquet",
                    "value_column": "in_universe",
                },
                "benchmark_weight": {
                    "path": str(data_dir / "benchmark_weight.parquet"),
                    "format": "parquet",
                    "value_column": "benchmark_weight",
                },
                "execution_price": {
                    "path": str(data_dir / "execution_price.parquet"),
                    "format": "parquet",
                    "value_column": "execution_price",
                },
                "position_unit_factor": {
                    "path": str(data_dir / "position_unit_factor.parquet"),
                    "format": "parquet",
                    "value_column": "position_unit_factor",
                },
            }
        },
        "backtest": {
            "initial_cash": 1_000_000.0,
            "execution_price": "execution_price",
            "position_unit_factor": "position_unit_factor",
            "universe": "universe",
            "benchmark_weight": "benchmark_weight",
        },
        "strategies": dict(configured_strategies),
    }
    config_path = root / "project.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return WorkflowProject(
        config_path=config_path,
        catalog_path=catalog_path,
        artifact_dir=artifact_dir,
        audit_path=audit_path,
        returns=returns,
    )


def strategy_config(
    *,
    scale: float,
    audit_path: Path,
    callable_name: str = "scaled_returns",
    **parameters: Any,
) -> dict[str, Any]:
    return {
        "callable": f"test_support.alpha_plugins:{callable_name}",
        "datasets": {"returns": "returns"},
        "parameters": {
            "scale": scale,
            "audit_path": str(audit_path),
            **parameters,
        },
    }


def run_by_strategy(outcome: Any) -> dict[str, Any]:
    return {run.strategy_id: run for run in outcome.runs}


def invocation_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _write_matrix(path: Path, matrix: pd.DataFrame, value_name: str) -> None:
    (
        matrix.stack(future_stack=True)
        .rename(value_name)
        .reset_index()
        .to_parquet(path, index=False)
    )
