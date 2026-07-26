from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))

from qlib_extended import (
    build_ensemble,
    create_report,
    open_run_catalog,
    run_strategy_batch,
)


def main() -> None:
    args = _parse_args()
    output_dir = args.output_dir.resolve()
    config_path, audit_path = _prepare_project(output_dir)
    invocations_before = _line_count(audit_path)

    first = run_strategy_batch(
        config_path,
        strategy_ids=("momentum", "reversal"),
        max_workers=2,
    )
    invocations_after_first = _line_count(audit_path)
    repeated = run_strategy_batch(
        config_path,
        strategy_ids=("momentum", "reversal"),
        max_workers=2,
    )
    invocations_after_repeat = _line_count(audit_path)
    _require_same_ids(first.runs, repeated.runs)

    members = {run.strategy_id: run for run in first.runs}
    ensemble = build_ensemble(
        output_dir / "runs.duckdb",
        strategy_id="ensemble.momentum_reversal",
        members={
            members["momentum"].alpha_run_id: 0.6,
            members["reversal"].alpha_run_id: 0.4,
        },
    )
    repeated_ensemble = build_ensemble(
        output_dir / "runs.duckdb",
        strategy_id="ensemble.momentum_reversal",
        members={
            members["momentum"].alpha_run_id: 0.6,
            members["reversal"].alpha_run_id: 0.4,
        },
    )
    if (
        repeated_ensemble.alpha_run_id != ensemble.alpha_run_id
        or repeated_ensemble.backtest_run_id != ensemble.backtest_run_id
    ):
        raise AssertionError("ensemble deterministic run IDs changed")

    html_only = create_report(
        output_dir / "runs.duckdb",
        backtest_run_ids=tuple(run.backtest_run_id for run in first.runs),
        output_dir=output_dir / "report-html-only",
    )
    with_figure = create_report(
        output_dir / "runs.duckdb",
        backtest_run_ids=(ensemble.backtest_run_id,),
        output_dir=output_dir / "report-with-figure",
        include_png=True,
    )
    catalog = open_run_catalog(output_dir / "runs.duckdb")
    records = catalog.list_runs()
    evidence = {
        "distribution": "qlib-extended",
        "python_import": "qlib_extended",
        "parallel_workers": 2,
        "first_runs": [asdict(run) for run in first.runs],
        "repeat_runs": [asdict(run) for run in repeated.runs],
        "deterministic_ids_stable": True,
        "strategy_invocations_after_first": invocations_after_first,
        "strategy_invocations_after_repeat": invocations_after_repeat,
        "strategy_invocations_added": invocations_after_first - invocations_before,
        "strategy_rerun_avoided": invocations_after_repeat == invocations_after_first,
        "ensemble": asdict(ensemble),
        "repeated_ensemble_cached": repeated_ensemble.cached,
        "catalog_run_count": len(records),
        "catalog_run_kinds": {
            kind: sum(record.run_kind == kind for record in records)
            for kind in ("alpha", "backtest")
        },
        "execution_backends": sorted(
            {
                record.metadata.get("execution_backend")
                for record in records
                if record.run_kind == "backtest"
            }
        ),
        "html_only_report": str(html_only.html_path),
        "html_only_files": [str(path) for path in html_only.files],
        "optional_png_report": [str(path) for path in with_figure.files],
        "duckdb_catalog": str(output_dir / "runs.duckdb"),
        "parquet_artifact_root": str(output_dir / "artifacts"),
    }
    expected_invocations = sum(not run.cached for run in first.runs)
    if (
        invocations_after_first - invocations_before != expected_invocations
        or invocations_after_repeat != invocations_after_first
    ):
        raise AssertionError("same effective config re-executed a strategy")
    if evidence["execution_backends"] != ["qlib"]:
        raise AssertionError("showcase did not use the Qlib execution backend")
    evidence_path = output_dir / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


def _prepare_project(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2024-01-02", periods=60)
    tickers = pd.Index(["A", "B", "C", "D"], name="ticker")
    phase = np.linspace(0.0, 4.0 * np.pi, len(dates))
    returns = pd.DataFrame(
        {
            "A": 0.0015 + 0.0040 * np.sin(phase),
            "B": 0.0008 + 0.0030 * np.cos(phase * 0.8),
            "C": -0.0002 + 0.0035 * np.sin(phase * 1.2 + 0.7),
            "D": 0.0004 + 0.0025 * np.cos(phase * 1.4 + 0.2),
        },
        index=dates,
        columns=tickers,
    ).rename_axis(index="date")
    execution_price = 100.0 * (1.0 + returns).cumprod()
    universe = pd.DataFrame(True, index=dates, columns=tickers).rename_axis("date")
    benchmark = pd.DataFrame(0.25, index=dates, columns=tickers).rename_axis("date")
    factor = pd.DataFrame(1.0, index=dates, columns=tickers).rename_axis("date")
    datasets = {
        "returns": (returns, "return"),
        "execution_price": (execution_price, "execution_price"),
        "universe": (universe, "in_universe"),
        "benchmark_weight": (benchmark, "benchmark_weight"),
        "position_unit_factor": (factor, "position_unit_factor"),
    }
    for name, (matrix, value_column) in datasets.items():
        path = data_dir / f"{name}.parquet"
        if not path.exists():
            _write_matrix(path, matrix, value_column)
    audit_path = output_dir / "strategy-invocations.txt"
    config = {
        "version": 1,
        "run_store": {
            "catalog_uri": str(output_dir / "runs.duckdb"),
            "artifact_dir": str(output_dir / "artifacts"),
        },
        "data": {
            "datasets": {
                name: {
                    "path": str(data_dir / f"{name}.parquet"),
                    "format": "parquet",
                    "value_column": value_column,
                }
                for name, (_, value_column) in datasets.items()
            }
        },
        "backtest": {
            "initial_cash": 100_000_000.0,
            "execution_price": "execution_price",
            "position_unit_factor": "position_unit_factor",
            "universe": "universe",
            "benchmark_weight": "benchmark_weight",
            "signal_lag": 1,
            "top_n": 2,
            "gross_exposure": 0.8,
        },
        "strategies": {
            name: {
                "callable": f"showcase.strategies:{name}_alpha",
                "datasets": {"returns": "returns"},
                "parameters": {"audit_path": str(audit_path)},
            }
            for name in ("momentum", "reversal")
        },
    }
    config_path = output_dir / "project.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return config_path, audit_path


def _write_matrix(path: Path, matrix: pd.DataFrame, value_column: str) -> None:
    (
        matrix.stack(future_stack=True)
        .rename(value_column)
        .reset_index()
        .to_parquet(path, index=False)
    )


def _require_same_ids(first, second) -> None:
    first_ids = [(run.alpha_run_id, run.backtest_run_id) for run in first]
    second_ids = [(run.alpha_run_id, run.backtest_run_id) for run in second]
    if first_ids != second_ids or not all(run.cached for run in second):
        raise AssertionError("same effective config did not reuse deterministic run IDs")


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the qlib-extended workflow showcase")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=INTEGRATION_ROOT / "outputs" / "workflow_showcase",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
