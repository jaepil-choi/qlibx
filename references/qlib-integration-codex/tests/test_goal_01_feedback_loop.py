from __future__ import annotations

import pandas as pd
import pytest

from _acceptance_contract import MarketScenario


def test_three_confirmed_losses_change_only_the_next_decision(backend_harness) -> None:
    dates = pd.bdate_range("2024-01-02", periods=5)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(
            {"A": [100.0, 90.0, 81.0, 72.9, 72.9]}, index=dates
        ),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
    )

    result = backend_harness.run_consecutive_loss_stop(
        scenario, consecutive_losses=3
    )

    assert [result.decision_weight(date, "A") for date in dates[:4]] == [
        1.0,
        1.0,
        1.0,
        1.0,
    ]
    assert result.decision_weight(dates[4], "A") == 0.0
    assert result.position_quantity(dates[4], "A") == 0
    feedback = result.feedback_audit()
    visible = feedback.dropna(subset=["feedback_date"])
    assert (visible["feedback_date"] < visible["decision_date"]).all()


def test_partial_fill_and_account_values_come_from_qlib_execution(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    scenario = MarketScenario(
        execution_price=pd.DataFrame(100.0, index=dates, columns=["A"]),
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        volume=pd.DataFrame({"A": [4.0, 1_000.0]}, index=dates),
        max_volume_participation=0.5,
        booksize=1_000.0,
    )
    targets = pd.DataFrame(1.0, index=dates, columns=["A"])

    result = backend_harness.run_weight_targets(scenario, targets)
    first_order = result.orders(dates[0]).iloc[-1]
    first_fill = result.fills(dates[0]).iloc[-1]

    assert first_order["requested_quantity"] == 10
    assert first_fill["filled_quantity"] == 2
    assert first_fill["reason"] == "partial_fill"
    assert result.position_quantity(dates[0], "A") == 2
    assert result.nav(dates[0]) == pytest.approx(
        result.cash(dates[0]) + 2 * 100.0
    )
    evidence = result.backend_evidence()
    assert evidence["execution_backend"] == "qlib"
    assert evidence["account_reconciliation_error"] <= 1e-8
