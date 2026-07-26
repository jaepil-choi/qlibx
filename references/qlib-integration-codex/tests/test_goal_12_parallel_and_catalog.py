from __future__ import annotations

from pathlib import Path

import yaml

from _workflow_contract import (
    invocation_count,
    load_public_api,
    make_project,
    run_by_strategy,
    strategy_config,
)


def test_worker_limit_above_one_executes_independent_strategies_concurrently(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    audit_path = tmp_path / "strategy-invocations.txt"
    marker_dir = tmp_path / "barrier"
    strategies = {
        "alpha_a": strategy_config(
            scale=1.0,
            audit_path=audit_path,
            callable_name="synchronized_scaled_returns",
            marker_dir=str(marker_dir),
            marker_name="a.ready",
            peer_marker_name="b.ready",
        ),
        "alpha_b": strategy_config(
            scale=-0.5,
            audit_path=audit_path,
            callable_name="synchronized_scaled_returns",
            marker_dir=str(marker_dir),
            marker_name="b.ready",
            peer_marker_name="a.ready",
        ),
    }
    project = make_project(tmp_path, strategies=strategies)

    outcome = api.run_strategy_batch(
        project.config_path,
        strategy_ids=("alpha_a", "alpha_b"),
        max_workers=2,
    )

    assert {run.status for run in outcome.runs} == {"complete"}
    assert (marker_dir / "a.ready").exists()
    assert (marker_dir / "b.ready").exists()


def test_same_effective_config_reuses_deterministic_run_ids(tmp_path: Path) -> None:
    api = load_public_api()
    project = make_project(tmp_path)

    first = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    second = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]

    assert first.alpha_run_id == second.alpha_run_id
    assert first.backtest_run_id == second.backtest_run_id
    assert invocation_count(project.audit_path) == 1
    reopened = api.open_run_catalog(project.catalog_path)
    records = {record.run_id: record for record in reopened.list_runs()}
    expected_ids = {
        first.alpha_run_id,
        first.backtest_run_id,
    }
    assert expected_ids == set(records)
    assert records[first.alpha_run_id].run_kind == "alpha"
    assert records[first.backtest_run_id].run_kind == "backtest"
    assert records[first.alpha_run_id].strategy_id == "alpha_a"
    assert records[first.alpha_run_id].status == "complete"
    assert records[first.alpha_run_id].dataset_fingerprint
    assert records[first.alpha_run_id].strategy_fingerprint


def test_backtest_config_change_reuses_alpha_and_only_changes_backtest_id(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    first = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]
    config = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    config["backtest"]["gross_exposure"] = 0.4
    project.config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    second = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )
    )["alpha_a"]

    assert second.alpha_run_id == first.alpha_run_id
    assert second.backtest_run_id != first.backtest_run_id
    assert invocation_count(project.audit_path) == 1
    records = api.open_run_catalog(project.catalog_path).list_runs()
    assert {record.run_kind for record in records} == {"alpha", "backtest"}
    assert len(records) == 3
