from __future__ import annotations

import pandas as pd

from _acceptance_contract import MarketScenario


def test_each_dataset_has_its_own_lookback_and_no_future_rows(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-04-01", periods=3)
    daily_dates = pd.bdate_range("2024-03-25", "2024-04-02")
    available_dates = pd.to_datetime(["2023-12-29", "2024-03-29"])
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        data={
            "daily_returns": pd.DataFrame(
                range(len(daily_dates)), index=daily_dates, columns=["A"]
            ),
            "quarterly_assets": pd.DataFrame(
                [10.0, 20.0], index=available_dates, columns=["A"]
            ),
        },
    )

    result = backend_harness.run_subscription_probe(
        scenario, {"daily_returns": 3, "quarterly_assets": 2}
    )
    audit = result.observation_audit()
    last = audit.loc[audit["decision_date"].eq(dates[-1])].set_index("dataset")

    assert last.loc["daily_returns", "row_count"] == 3
    assert last.loc["quarterly_assets", "row_count"] == 2
    assert last.loc["daily_returns", "max_observation_date"] == dates[-2]
    assert last.loc["quarterly_assets", "max_observation_date"] == pd.Timestamp(
        "2024-03-29"
    )
    assert (audit["max_observation_date"] < audit["decision_date"]).all()


def test_strategy_memory_persists_within_run_and_resets_for_new_run(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=3)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )

    first = backend_harness.run_stateful_probe(scenario).state_audit()
    second = backend_harness.run_stateful_probe(scenario).state_audit()

    assert first["memory_counter"].tolist() == [1, 2, 3]
    assert second["memory_counter"].tolist() == [1, 2, 3]
