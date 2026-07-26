from __future__ import annotations

from pathlib import Path

from _workflow_contract import (
    invocation_count,
    load_public_api,
    make_project,
    run_by_strategy,
)


def test_report_is_built_from_stored_runs_without_strategy_rerun(
    monkeypatch,
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    run = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    invocations_before = invocation_count(project.audit_path)
    monkeypatch.setenv("KWAM_TEST_FORBID_ALPHA_EXECUTION", "1")

    report = api.create_report(
        project.catalog_path,
        backtest_run_ids=(run.backtest_run_id,),
        output_dir=tmp_path / "report",
    )

    assert report.backtest_run_ids == (run.backtest_run_id,)
    assert report.html_path.exists()
    assert report.files == (report.html_path,)
    assert run.backtest_run_id in report.html_path.read_text(encoding="utf-8")
    assert not list((tmp_path / "report").glob("*.csv"))
    assert not list((tmp_path / "report").glob("*.parquet"))
    assert not list((tmp_path / "report").glob("*.png"))
    assert invocation_count(project.audit_path) == invocations_before

    report_with_png = api.create_report(
        project.catalog_path,
        backtest_run_ids=(run.backtest_run_id,),
        output_dir=tmp_path / "report-with-png",
        include_png=True,
    )
    assert report_with_png.html_path.exists()
    assert report_with_png.png_paths
    assert all(path.stat().st_size > 0 for path in report_with_png.png_paths)
    assert invocation_count(project.audit_path) == invocations_before
