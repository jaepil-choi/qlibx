from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from _workflow_contract import (
    load_public_api,
    make_project,
    run_by_strategy,
)


def test_config_drives_data_loading_and_multiple_strategy_runs(tmp_path: Path) -> None:
    api = load_public_api()
    project = make_project(tmp_path)

    outcome = api.run_strategy_batch(
        project.config_path,
        strategy_ids=("alpha_a", "alpha_b"),
        max_workers=1,
    )

    runs = run_by_strategy(outcome)
    assert set(runs) == {"alpha_a", "alpha_b"}
    assert all(run.status == "complete" for run in runs.values())
    assert all(run.alpha_run_id for run in runs.values())
    assert all(run.backtest_run_id for run in runs.values())
    assert all(
        run.alpha_run_id != run.backtest_run_id for run in runs.values()
    )
    catalog = api.open_run_catalog(project.catalog_path)
    pd.testing.assert_frame_equal(
        catalog.load_alpha(runs["alpha_a"].alpha_run_id),
        project.returns,
        check_freq=False,
    )
    pd.testing.assert_frame_equal(
        catalog.load_alpha(runs["alpha_b"].alpha_run_id),
        project.returns * -0.5,
        check_freq=False,
    )
    for run in runs.values():
        account = catalog.load_table(run.backtest_run_id, "account_daily")
        assert not account.empty
        assert {"trade_date", "nav", "portfolio_return"} <= set(account.columns)
        backtest_record = catalog.get_run(run.backtest_run_id)
        assert backtest_record.parent_run_ids == (run.alpha_run_id,)


def test_unknown_logical_dataset_fails_before_strategy_execution(
    tmp_path: Path,
) -> None:
    api = load_public_api()
    project = make_project(tmp_path)
    config = yaml.safe_load(project.config_path.read_text(encoding="utf-8"))
    config["strategies"]["alpha_a"]["datasets"]["returns"] = "missing_returns"
    project.config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(api.ConfigurationError, match="missing_returns"):
        api.run_strategy_batch(
            project.config_path,
            strategy_ids=("alpha_a",),
            max_workers=1,
        )

    assert not project.audit_path.exists()
