import csv
import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from qlibx import QlibxProject
from qlibx.config import ChangeAction

SAMPLE_ID = "constraint-workflow-v1"


def sample_source() -> Path:
    return (
        Path(__file__).parents[1]
        / "src"
        / "qlibx"
        / "resources"
        / "samples"
        / "constraint_workflow"
    )


def test_constraint_sample_rows_reconcile_to_real_sources() -> None:
    root = Path(__file__).parents[1]
    expected_weights = dict(
        duckdb.connect()
        .sql(
            f"""
            SELECT ticker, index_weight
            FROM read_parquet('{(root / 'data/preprocessed/k200_members.parquet').as_posix()}')
            WHERE date = DATE '2024-01-02'
              AND ticker IN ('A005930', 'A000660')
            """
        )
        .fetchall()
    )
    with (sample_source() / "benchmark.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        benchmark_rows = tuple(csv.DictReader(handle))

    assert len(benchmark_rows) == len(expected_weights) == 2
    for row in benchmark_rows:
        assert float(row["benchmark_weight"]) == expected_weights[row["ticker"]]
        assert row["observation_time"] == "2024-01-02T09:00:00+09:00"
        assert row["available_at"] == "2024-01-03T09:00:00+09:00"

    columns = (
        "{'ticker':'VARCHAR','trade_date':'BIGINT','base_price':'DOUBLE',"
        "'open_price':'DOUBLE','high_price':'DOUBLE','low_price':'DOUBLE',"
        "'close_price':'DOUBLE','prev_close':'DOUBLE','adjustment_factor':'DOUBLE',"
        "'volume':'DOUBLE','amount':'DOUBLE','shares':'DOUBLE',"
        "'listing_type':'VARCHAR','change_type':'VARCHAR','halt_code':'DOUBLE',"
        "'admin_code':'DOUBLE'}"
    )
    expected_prices = dict(
        duckdb.connect()
        .sql(
            f"""
            SELECT ticker, close_price
            FROM read_csv(
                '{(root / 'data/DW/fng_stock_daily_prices.csv').as_posix()}',
                header = true,
                columns = {columns}
            )
            WHERE trade_date = 20240103
              AND ticker IN ('A005930', 'A000660')
            """
        )
        .fetchall()
    )
    with (sample_source() / "lots.csv").open(encoding="utf-8", newline="") as handle:
        lot_rows = tuple(csv.DictReader(handle))

    assert len(lot_rows) == len(expected_prices) == 2
    for row in lot_rows:
        assert float(row["price"]) == expected_prices[row["ticker"]]
        assert float(row["lot_size"]) == 1


def test_constraint_sample_materializes_and_runs_deterministically(tmp_path: Path) -> None:
    root = tmp_path / "constraint-sample-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample(SAMPLE_ID)
    assert preview.sample_id == SAMPLE_ID
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)

    applied = project.materialize_sample(SAMPLE_ID, apply=True)
    repeated_materialization = project.materialize_sample(SAMPLE_ID, apply=True)
    assert applied.applied is repeated_materialization.applied is True
    assert all(
        change.action is ChangeAction.UNCHANGED
        for change in repeated_materialization.changes
    )

    script = root / "examples" / "qlibx_owned" / "constraint_workflow" / "run.py"

    def run_sample() -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(script), str(root)],
            check=True,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    first = run_sample()
    repeated = run_sample()
    assert first == repeated
    assert first["original_weights"] == {"A000660": -0.4, "A005930": 0.6}
    assert first["adjusted_weights"]["A000660"] == 0.0
    assert first["adjusted_weights"]["A005930"] == pytest.approx(
        0.31752577319587627
    )
    assert first["unresolved_excess"] == pytest.approx(0.00032577319587628883)
    assert first["eligible"] is False
    assert first["failed_findings"] == [
        {
            "bound": 0.3172,
            "excess": pytest.approx(0.00032577319587628883),
            "instrument": "A005930",
            "measured": pytest.approx(0.31752577319587627),
            "metric": "single_name_cap",
        }
    ]
    assert first["adjustment_dataset_ids"] == ["sample-k200-benchmark"]
    assert first["validation_dataset_ids"] == ["sample-k200-benchmark"]
    assert first["artifact_types"] == [
        "constraint_adjustment_result",
        "constraint_validation_result",
        "portfolio_construction_result",
        "strategy_result",
    ]

    readme = root / "examples" / "qlibx_owned" / "constraint_workflow" / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nuser edit\n",
        encoding="utf-8",
    )
    conflict = project.materialize_sample(SAMPLE_ID, apply=True)
    assert conflict.applied is False
    assert "refusing to overwrite" in (conflict.error or "")
    assert readme.read_text(encoding="utf-8").endswith("user edit\n")


def test_constraint_sample_is_separate_from_existing_samples(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    project = QlibxProject.open(tmp_path)

    basic = project.materialize_sample()
    constraint = project.materialize_sample(SAMPLE_ID)
    daily = project.materialize_sample("daily-closed-loop-v1")

    assert Path(basic.destination).parts[-2:] == ("qlibx_owned", "basic")
    assert Path(constraint.destination).parts[-2:] == (
        "qlibx_owned",
        "constraint_workflow",
    )
    assert Path(daily.destination).parts[-2:] == ("qlibx_owned", "daily_closed_loop")
    assert {basic.sample_id, constraint.sample_id, daily.sample_id} == {
        "basic-real-dw-journey-v1",
        "constraint-workflow-v1",
        "daily-closed-loop-v1",
    }