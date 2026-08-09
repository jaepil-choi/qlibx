import csv
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest

from qlibx import QlibxProject
from qlibx.cli import run
from qlibx.config import ChangeAction
from qlibx.sample import SampleMaterializer


def _output(capsys: object) -> object:
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    return json.loads(captured.out)


def test_bundled_sample_rows_reconcile_to_real_dw() -> None:
    root = Path(__file__).parents[1]
    source = root / "data" / "DW" / "fng_stock_daily_prices.csv"
    sample = root / "src" / "qlibx" / "resources" / "samples" / "basic" / "market.csv"
    columns = (
        "{'ticker':'VARCHAR','trade_date':'BIGINT','base_price':'DOUBLE',"
        "'open_price':'DOUBLE','high_price':'DOUBLE','low_price':'DOUBLE',"
        "'close_price':'DOUBLE','prev_close':'DOUBLE','adjustment_factor':'DOUBLE',"
        "'volume':'DOUBLE','amount':'DOUBLE','shares':'DOUBLE',"
        "'listing_type':'VARCHAR','change_type':'VARCHAR','halt_code':'DOUBLE',"
        "'admin_code':'DOUBLE'}"
    )
    expected = {
        (str(trade_date), ticker): decision_return
        for trade_date, ticker, decision_return in duckdb.connect()
        .sql(
            f"""
            SELECT trade_date, ticker, close_price / base_price - 1
            FROM read_csv('{source.as_posix()}', header = true, columns = {columns})
            WHERE ticker IN ('A005930', 'A000660')
              AND trade_date IN (20240102, 20240103)
            """
        )
        .fetchall()
    }
    with sample.open(encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))

    assert len(rows) == len(expected) == 4
    for row in rows:
        session = row["date"][:10].replace("-", "")
        assert float(row["decision_return"]) == pytest.approx(expected[(session, row["ticker"])])
        assert row["date"].endswith("T09:00:00+09:00")
        assert row["available_at"].endswith("T15:30:00+09:00")


def test_opt_in_sample_materializes_and_runs_through_public_surface(
    tmp_path: Path,
    capsys: object,
    run_python_subprocess: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    root = tmp_path / "sample-project"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    preview = project.materialize_sample()
    assert preview.applied is False
    assert all(change.action is ChangeAction.CREATE for change in preview.changes)
    assert not (root / "examples").exists()

    applied = project.materialize_sample(apply=True)
    repeated = project.materialize_sample(apply=True)
    assert applied.applied is repeated.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in repeated.changes)
    script = root / "examples" / "qlibx_owned" / "basic" / "run.py"
    completed = run_python_subprocess((script, root), check=True, cwd=root)
    result = json.loads(completed.stdout)
    assert result["direct_weights"] == {"A005930": 1.0}
    assert result["stored_consumer_count"] == 2
    assert result["portfolio_weights"] == {"A005930": 1.0}
    assert result["analysis_metrics"]["signal_count"] == 2.0
    assert result["analysis_metrics"]["information_coefficient"] == 1.0
    assert set(result["artifact_types"]) == {
        "analysis_result",
        "portfolio_construction_result",
        "report_result",
        "stored_signal_result",
        "strategy_result",
    }

    assert run(["artifact", "show", str(root), result["report_artifact_id"]]) == 0
    shown = _output(capsys)
    assert shown["artifact_type"] == "report_result"


def test_sample_cli_is_preview_first_and_refuses_modified_files(
    tmp_path: Path,
    capsys: object,
) -> None:
    QlibxProject.init(tmp_path, apply=True)
    assert run(["project", "sample", str(tmp_path)]) == 0
    preview = _output(capsys)
    assert preview["applied"] is False
    assert not (tmp_path / "examples").exists()

    assert run(["project", "sample", str(tmp_path), "--apply"]) == 0
    _output(capsys)
    readme = tmp_path / "examples" / "qlibx_owned" / "basic" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nuser edit\n", encoding="utf-8")

    assert run(["project", "sample", str(tmp_path), "--apply"]) == 1
    conflict = _output(capsys)
    assert conflict["applied"] is False
    assert "refusing to overwrite" in conflict["error"]
    assert readme.read_text(encoding="utf-8").endswith("user edit\n")


@pytest.mark.parametrize(
    ("sample_id", "directory_name"),
    (
        ("basic-real-dw-journey-v1", "basic"),
        ("constraint-workflow-v1", "constraint_workflow"),
        ("daily-closed-loop-v1", "daily_closed_loop"),
        ("strategy-composition-v1", "strategy_composition"),
        ("strategy-extension-v1", "strategy_extension"),
    ),
)
def test_sample_cli_selects_each_bundled_sample(
    tmp_path: Path,
    capsys: object,
    sample_id: str,
    directory_name: str,
) -> None:
    root = tmp_path / sample_id
    QlibxProject.init(root, apply=True)

    assert run(["project", "sample", str(root), "--sample-id", sample_id]) == 0
    preview = _output(capsys)

    assert preview["sample_id"] == sample_id
    assert Path(preview["destination"]).name == directory_name
    assert {change["action"] for change in preview["changes"]} == {"create"}


def test_sample_ids_match_bundled_directories_and_cli_rejects_unknown(
    tmp_path: Path,
) -> None:
    QlibxProject.init(tmp_path, apply=True)
    project = QlibxProject.open(tmp_path)
    destination_names = {
        Path(project.materialize_sample(sample_id).destination).name
        for sample_id in SampleMaterializer.sample_ids()
    }
    resource_root = Path(__file__).parents[1] / "src" / "qlibx" / "resources" / "samples"
    bundled_names = {path.name for path in resource_root.iterdir() if path.is_dir()}

    assert SampleMaterializer.sample_ids() == QlibxProject.available_sample_ids()
    assert destination_names == bundled_names
    with pytest.raises(SystemExit) as exc_info:
        run(["project", "sample", str(tmp_path), "--sample-id", "nope"])
    assert exc_info.value.code == 2
