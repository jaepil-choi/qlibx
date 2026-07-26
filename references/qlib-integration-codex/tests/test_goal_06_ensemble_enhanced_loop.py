from __future__ import annotations

import pandas as pd

from _acceptance_contract import MarketScenario


def test_cached_long_short_members_can_build_one_enhanced_index_run(
    backend_harness,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=2)
    members = {
        "member_a": pd.DataFrame(
            [[1.0, -1.0], [1.0, -1.0]], index=dates, columns=["A", "B"]
        ),
        "member_b": pd.DataFrame(
            [[-1.0, 1.0], [-1.0, 1.0]], index=dates, columns=["A", "B"]
        ),
    }
    scenario = MarketScenario(
        execution_price=pd.DataFrame(
            100.0, index=dates, columns=["A", "B", "K200_ETF"]
        ),
        universe=pd.DataFrame(True, index=dates, columns=["A", "B"]),
        asset_class=pd.Series(
            {"A": "stock", "B": "stock", "K200_ETF": "etf"}
        ),
        booksize=10_000.0,
        position_unit_factor=pd.DataFrame(
            1.0, index=dates, columns=["A", "B", "K200_ETF"]
        ),
    )

    result = backend_harness.run_cached_ensemble(
        scenario, members, etf_weight=0.30
    )

    research = result.research_evaluations()
    combined = research.loc[research["candidate_id"].eq("combined_alpha")]
    assert combined["score"].abs().max() <= 1e-12
    assert set(result.orders()["instrument_id"]) <= {"A", "B", "K200_ETF"}
    assert "K200_ETF" in set(result.positions()["instrument_id"])
    assert result.backend_evidence()["member_strategy_invocations"] == 0
    assert result.backend_evidence()["execution_backend"] == "qlib"
