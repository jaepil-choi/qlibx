from __future__ import annotations

import pandas as pd
import pytest

from _acceptance_contract import MarketScenario


def _scenario() -> tuple[MarketScenario, pd.DatetimeIndex]:
    dates = pd.bdate_range("2024-01-02", periods=6)
    universe = pd.DataFrame(
        [
            [True, False],
            [True, True],
            [False, True],
            [False, True],
            [False, True],
            [True, True],
        ],
        index=dates,
        columns=["A", "B"],
    )
    sellable = pd.DataFrame(True, index=dates, columns=["A", "B"])
    sellable.loc[dates[2], "A"] = False
    return (
        MarketScenario(
            execution_price=pd.DataFrame(
                100.0, index=dates, columns=["A", "B"]
            ),
            universe=universe,
            sellable=sellable,
            booksize=10_000.0,
            position_unit_factor=pd.DataFrame(
                1.0, index=dates, columns=["A", "B"]
            ),
        ),
        dates,
    )


def test_entry_exit_blocked_liquidation_and_reentry_are_observable(
    backend_harness,
) -> None:
    scenario, dates = _scenario()
    result = backend_harness.run_universe_probe(
        scenario, reentry_policy="reset"
    )

    assert result.decision_weight(dates[0], "B") == 0.0
    assert result.decision_weight(dates[1], "B") > 0.0
    assert result.decision_weight(dates[2], "A") == 0.0
    assert result.position_quantity(dates[2], "A") > 0
    blocked = result.fills(dates[2]).query("instrument_id == 'A'").iloc[-1]
    assert blocked["filled_quantity"] == 0
    assert blocked["reason"] == "sell_blocked"
    assert result.position_quantity(dates[3], "A") == 0
    assert result.position_quantity(dates[5], "A") > 0


def test_reentry_memory_policy_must_be_explicit(backend_harness) -> None:
    scenario, _ = _scenario()
    with pytest.raises(ValueError, match="reentry"):
        backend_harness.run_universe_probe(scenario, reentry_policy=None)
