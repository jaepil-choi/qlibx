import csv
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from qlibx import QlibxProject
from qlibx.config import ChangeAction

SAMPLE_ID = "daily-closed-loop-v1"


def test_daily_sample_rows_reconcile_to_real_dw() -> None:
    root = Path(__file__).parents[1]
    source = root / "data" / "DW" / "fng_stock_daily_prices.csv"
    sample = (
        root
        / "src"
        / "qlibx"
        / "resources"
        / "samples"
        / "daily_closed_loop"
        / "market.csv"
    )
    columns = (
        "{'ticker':'VARCHAR','trade_date':'BIGINT','base_price':'DOUBLE',"
        "'open_price':'DOUBLE','high_price':'DOUBLE','low_price':'DOUBLE',"
        "'close_price':'DOUBLE','prev_close':'DOUBLE','adjustment_factor':'DOUBLE',"
        "'volume':'DOUBLE','amount':'DOUBLE','shares':'DOUBLE',"
        "'listing_type':'VARCHAR','change_type':'VARCHAR','halt_code':'DOUBLE',"
        "'admin_code':'DOUBLE'}"
    )
    expected = {
        (str(trade_date), ticker): (decision_return, close_price)
        for trade_date, ticker, decision_return, close_price in duckdb.connect()
        .sql(
            f"""
            SELECT trade_date, ticker, close_price / base_price - 1, close_price
            FROM read_csv('{source.as_posix()}', header = true, columns = {columns})
            WHERE ticker IN ('A005930', 'A000660')
              AND trade_date BETWEEN 20240102 AND 20240105
            """
        )
        .fetchall()
    }
    with sample.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))

    assert len(rows) == len(expected) == 8
    for row in rows:
        session = row["date"][:10].replace("-", "")
        decision_return, close_price = expected[(session, row["ticker"])]
        assert float(row["decision_return"]) == pytest.approx(decision_return)
        assert float(row["close"]) == pytest.approx(close_price)
        assert row["date"].endswith("T09:00:00+09:00")
        assert row["available_at"].endswith("T15:30:00+09:00")


def test_daily_sample_materializes_and_runs_public_closed_loop(
    tmp_path: Path,
    run_python_subprocess: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    root = tmp_path / "daily-sample-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample(SAMPLE_ID)
    assert preview.sample_id == SAMPLE_ID
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)

    applied = project.materialize_sample(SAMPLE_ID, apply=True)
    repeated = project.materialize_sample(SAMPLE_ID, apply=True)
    assert applied.applied is repeated.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)

    script = root / "examples" / "qlibx_owned" / "daily_closed_loop" / "run.py"
    completed = run_python_subprocess((script, root), check=True, cwd=root)
    result = json.loads(completed.stdout)

    assert result["selected_instruments"] == ["A005930", "A000660"]
    assert result["execution_count"] == 2
    assert result["feedback_ranges"] == [[0, 0], [0, 2]]
    assert result["final_positions"] == {"A000660": 72.0}
    assert result["checkpoint_run_id"] == "sample-daily-closed-loop"
    assert {item["side"] for item in result["fills"]} == {"BUY", "SELL"}
    assert {
        "decision_intent",
        "execution_result",
        "mark_result",
        "memory_commit",
        "session_performance",
        "simulation_checkpoint",
        "strategy_result",
    }.issubset(result["artifact_types"])

    readme = root / "examples" / "qlibx_owned" / "daily_closed_loop" / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nuser edit\n",
        encoding="utf-8",
    )
    conflict = project.materialize_sample(SAMPLE_ID, apply=True)
    assert conflict.applied is False
    assert "refusing to overwrite" in (conflict.error or "")
    assert readme.read_text(encoding="utf-8").endswith("user edit\n")


def test_daily_sample_is_separate_and_unknown_id_is_rejected(tmp_path: Path) -> None:
    QlibxProject.init(tmp_path, apply=True)
    project = QlibxProject.open(tmp_path)

    basic = project.materialize_sample()
    daily = project.materialize_sample(SAMPLE_ID)
    assert basic.sample_id == "basic-real-dw-journey-v1"
    assert Path(basic.destination).parts[-2:] == ("qlibx_owned", "basic")
    assert Path(daily.destination).parts[-2:] == ("qlibx_owned", "daily_closed_loop")

    with pytest.raises(ValueError, match="unknown bundled sample_id"):
        project.materialize_sample("unknown-sample")