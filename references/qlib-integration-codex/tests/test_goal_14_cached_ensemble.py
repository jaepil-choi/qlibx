from __future__ import annotations

from pathlib import Path

import pandas as pd

from _workflow_contract import (
    invocation_count,
    load_public_api,
    make_project,
    run_by_strategy,
)


def test_ensemble_uses_member_run_ids_and_publishes_reusable_alpha(
    monkeypatch,
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    members = run_by_strategy(
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a", "alpha_b"),
            max_workers=2,
        )
    )
    invocations_before = invocation_count(project.audit_path)
    monkeypatch.setenv("KWAM_TEST_FORBID_ALPHA_EXECUTION", "1")

    ensemble = api.build_ensemble(
        project.catalog_path,
        strategy_id="ensemble.weighted",
        members={
            members["alpha_a"].alpha_run_id: 0.75,
            members["alpha_b"].alpha_run_id: 0.25,
        },
    )

    assert ensemble.status == "complete"
    assert ensemble.alpha_run_id not in {
        run.alpha_run_id for run in members.values()
    }
    assert ensemble.alpha_run_id != ensemble.backtest_run_id
    catalog = api.open_run_catalog(project.catalog_path)
    pd.testing.assert_frame_equal(
        catalog.load_alpha(ensemble.alpha_run_id),
        project.returns * 0.625,
        check_freq=False,
    )
    stored = catalog.get_run(ensemble.alpha_run_id)
    assert set(stored.parent_run_ids) == {
        members["alpha_a"].alpha_run_id,
        members["alpha_b"].alpha_run_id,
    }
    backtest = catalog.get_run(ensemble.backtest_run_id)
    assert backtest.parent_run_ids == (ensemble.alpha_run_id,)
    assert not catalog.load_table(ensemble.backtest_run_id, "account_daily").empty
    assert invocation_count(project.audit_path) == invocations_before

    repeated = api.build_ensemble(
        project.catalog_path,
        strategy_id="ensemble.weighted",
        members={
            members["alpha_a"].alpha_run_id: 0.75,
            members["alpha_b"].alpha_run_id: 0.25,
        },
    )
    assert repeated.alpha_run_id == ensemble.alpha_run_id
    assert repeated.backtest_run_id == ensemble.backtest_run_id
    assert repeated.cached
