from __future__ import annotations

import pandas as pd

from _acceptance_contract import MarketScenario


def test_historical_what_if_changes_rule_without_mutating_actual_account(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=8)
    payoff = pd.DataFrame(
        {
            "momentum": [1.0, 1.0, 1.0, -2.0, -2.0, -2.0, -2.0, -2.0],
            "reversal": [-1.0, -1.0, -1.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        },
        index=dates,
    )
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        data={"candidate_payoff": payoff},
    )

    result = backend_harness.run_adaptive_rules(
        scenario, ("momentum", "reversal"), lookback=3
    )
    evaluations = result.research_evaluations()

    assert result.selected_rule(dates[3]) == "momentum"
    assert result.selected_rule(dates[6]) == "reversal"
    visible = evaluations.dropna(subset=["max_observation_date"])
    assert (visible["max_observation_date"] < visible["trade_date"]).all()
    assert evaluations["actual_orders_during_evaluation"].eq(0).all()
    assert evaluations["actual_cash_delta_during_evaluation"].eq(0.0).all()
    assert evaluations["actual_position_delta_during_evaluation"].eq(0).all()


def test_model_training_is_causal_and_rule_changes_only_after_retraining(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=10)
    feature = pd.Series([1.0, -1.0] * 5, index=dates)
    relation = pd.Series([1.0] * 5 + [-1.0] * 5, index=dates)
    dataset = pd.DataFrame(
        {"feature": feature, "realized_return": feature * relation}, index=dates
    )
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        data={"adaptive_training": dataset},
    )

    result = backend_harness.run_adaptive_model(
        scenario, train_dataset="adaptive_training", retrain_every=2
    )
    state = result.state_audit().dropna(subset=["training_max_date"])

    assert (state["training_max_date"] < state["decision_date"]).all()
    changed = state["model_version"].ne(state["model_version"].shift())
    assert state.loc[~changed, "retrained"].eq(False).all()
    assert result.selected_rule(dates[4]) != result.selected_rule(dates[-1])
