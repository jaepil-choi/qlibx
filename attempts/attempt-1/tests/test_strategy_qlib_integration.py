from __future__ import annotations

import pandas as pd

from qlibx.execution import SignedExecutionConfig, run_strategy_execution
from qlibx.strategy import DecisionContext, DecisionResult, StrategyDefinition


def _definition() -> StrategyDefinition:
    return StrategyDefinition(
        "adaptive.v1",
        "adaptive",
        {},
        ("returns",),
        "weight",
        version="1",
    )


def _program(context: DecisionContext, _parameters) -> DecisionResult:
    feedback_count = len(context.feedback_history)
    weight = 0.5 if feedback_count == 0 else 0.8
    payload = pd.Series({"A": weight})
    return DecisionResult(
        "weight",
        payload,
        memory={"decisions": int(context.memory.get("decisions", 0)) + 1},
        diagnostics={
            "feedback_count": feedback_count,
            "latest_feedback": (
                None
                if not context.feedback_history
                else context.feedback_history[-1].confirmed_at.isoformat()
            ),
            "bounded_rows": len(context.datasets["returns"]),
            "account_nav": float(context.account["nav"]),
        },
    )


def _inputs(periods: int = 5):
    dates = pd.bdate_range("2025-01-02", periods=periods)
    returns = pd.DataFrame({"A": range(periods)}, index=dates, dtype="float64")
    available = pd.DataFrame(
        {"A": dates - pd.Timedelta(days=1)},
        index=dates,
    )
    price = pd.DataFrame({"A": [10.0] * periods}, index=dates)
    lifecycle = pd.DataFrame({"A": [True] * periods}, index=dates)
    volume = pd.DataFrame({"A": [1_000.0] * periods}, index=dates)
    return dates, {
        "datasets": {"returns": returns},
        "availability": {"returns": available},
        "dataset_ids": {"returns": "returns-pit-v1"},
        "lookback_rows": {"returns": 2},
        "execution_price": price,
        "valuation_price": price,
        "universe": lifecycle,
        "tradable": lifecycle,
        "volume": volume,
        "initial_cash": 1_000.0,
        "effective_config_id": "frozen-config-1",
    }


def test_strategy_decision_sees_only_prior_qlib_confirmed_feedback() -> None:
    dates, inputs = _inputs()
    result = run_strategy_execution(_definition(), _program, **inputs)
    assert [decision.diagnostics["feedback_count"] for decision in result.decisions] == [
        0,
        1,
        2,
        3,
        4,
    ]
    assert result.decisions[0].diagnostics["latest_feedback"] is None
    assert result.decisions[1].diagnostics["latest_feedback"] == dates[0].isoformat()
    assert [decision.diagnostics["bounded_rows"] for decision in result.decisions] == [
        2,
        2,
        2,
        2,
        2,
    ]
    assert result.evidence["execution_backend"] == "qlib"
    assert result.evidence["feedback_order"] == "previous_qlib_confirmed_only"
    assert result.fills.loc[result.fills["trade_date"].eq(dates[0]), "filled_quantity"].sum() > 0
    assert pd.isna(result.feedback_audit.iloc[0]["feedback_date"])
    assert result.feedback_audit.iloc[1]["feedback_date"] == dates[0]


def test_strategy_and_qlib_checkpoint_resume_match_uninterrupted() -> None:
    _dates, inputs = _inputs(periods=6)
    full = run_strategy_execution(_definition(), _program, **inputs)
    prefix = run_strategy_execution(_definition(), _program, **inputs, end_position=3)
    suffix = run_strategy_execution(
        _definition(),
        _program,
        **inputs,
        start_position=3,
        checkpoint=prefix.checkpoint,
    )
    combined_decisions = prefix.decisions + suffix.decisions
    assert [item.result_id for item in combined_decisions] == [
        item.result_id for item in full.decisions
    ]
    assert suffix.checkpoint.memory == full.checkpoint.memory
    assert suffix.checkpoint.previous_result_id == full.checkpoint.previous_result_id
    for name in ("orders", "fills", "positions", "account"):
        actual = pd.concat([getattr(prefix, name), getattr(suffix, name)]).reset_index(drop=True)
        expected = getattr(full, name).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected)


def _signed_program(context: DecisionContext, _parameters) -> DecisionResult:
    latest_nav = None if not context.feedback else float(context.feedback["nav"])
    weight = 0.0 if latest_nav is None or latest_nav > 1_000.0 else -0.2
    return DecisionResult(
        "weight",
        pd.Series({"A": weight}),
        memory={"decisions": int(context.memory.get("decisions", 0)) + 1},
        diagnostics={
            "feedback_count": len(context.feedback_history),
            "latest_active_nav": latest_nav,
            "actual_signed_quantity": float(context.account["held_quantity"]["A"]),
            "active_nav_before_decision": float(context.account["nav"]),
        },
    )


def _signed_inputs():
    dates, inputs = _inputs(periods=4)
    inputs.update(
        {
            "execution_price": pd.DataFrame({"A": [10.0, 10.0, 10.0, 8.0]}, index=dates),
            "valuation_price": pd.DataFrame({"A": [10.0, 10.0, 8.0, 8.0]}, index=dates),
            "volume": pd.DataFrame({"A": [1_000.0, 5.0, 1_000.0, 1_000.0]}, index=dates),
            "initial_cash": 3_000.0,
            "signed": SignedExecutionConfig(
                observed=pd.DataFrame({"A": [False, True, True, True]}, index=dates),
                shortable=pd.DataFrame({"A": [False, True, True, True]}, index=dates),
                active_booksize=1_000.0,
                per_name_short_cap=0.3,
                inventory_retention="active_short_only",
            ),
        }
    )
    return dates, inputs


def test_signed_strategy_is_adaptive_to_confirmed_active_feedback() -> None:
    dates, inputs = _signed_inputs()
    result = run_strategy_execution(_definition(), _signed_program, **inputs)

    assert result.mode == "matched_capitalization"
    assert result.signed is not None
    assert result.evidence["decision_semantics"] == "signed_weight"
    assert [item.diagnostics["feedback_count"] for item in result.decisions] == [0, 1, 2, 3]
    assert result.decisions[2].diagnostics["actual_signed_quantity"] == -5.0
    assert result.decisions[3].diagnostics["latest_active_nav"] == 1_040.0
    assert result.signed.intended_weights.loc[dates].iloc[:, 0].tolist() == [
        0.0,
        -0.2,
        -0.2,
        0.0,
    ]
    first_sell = result.orders.loc[result.orders["trade_date"].eq(dates[1])].iloc[0]
    first_fill = result.fills.loc[result.fills["trade_date"].eq(dates[1])].iloc[0]
    assert first_sell["direction"] == "sell"
    assert first_fill["filled_quantity"] == 5
    signed_day = result.positions.loc[result.positions["trade_date"].eq(dates[1])].iloc[0]
    assert signed_day["held_quantity"] == -5
    assert result.account.iloc[-1]["nav"] == result.signed.active_account.iloc[-1]["nav"]


def test_signed_strategy_checkpoint_resume_matches_uninterrupted() -> None:
    _dates, inputs = _signed_inputs()
    full = run_strategy_execution(_definition(), _signed_program, **inputs)
    prefix = run_strategy_execution(_definition(), _signed_program, **inputs, end_position=2)
    suffix = run_strategy_execution(
        _definition(),
        _signed_program,
        **inputs,
        start_position=2,
        checkpoint=prefix.checkpoint,
    )
    assert [item.result_id for item in prefix.decisions + suffix.decisions] == [
        item.result_id for item in full.decisions
    ]
    assert prefix.signed is not None and suffix.signed is not None and full.signed is not None
    for name in (
        "orders",
        "fills",
        "signed_positions",
        "composite_account",
        "baseline_account",
        "active_account",
        "capitalization_events",
    ):
        actual = pd.concat(
            [getattr(prefix.signed, name), getattr(suffix.signed, name)]
        ).reset_index(drop=True)
        expected = getattr(full.signed, name).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected)
