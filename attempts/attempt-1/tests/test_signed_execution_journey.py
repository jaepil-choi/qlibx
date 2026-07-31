from __future__ import annotations

import pandas as pd
import pytest

from qlibx.execution import run_signed_execution


def _inputs(
    *,
    intents=(0.0, -0.2, -0.2, 0.0),
    prices=(10.0, 10.0, 10.0, 10.0),
    volumes=(1_000.0, 1_000.0, 1_000.0, 1_000.0),
    tradable=(True, True, True, True),
    initial_cash=2_000.0,
    active_booksize=1_000.0,
    inventory_retention="retained",
    per_name_short_cap=0.3,
):
    dates = pd.bdate_range("2025-01-02", periods=len(intents))
    columns = ["IPO"]

    def frame(values):
        return pd.DataFrame([[value] for value in values], index=dates, columns=columns)

    return {
        "dates": dates,
        "kwargs": {
            "signed_weights": frame(intents),
            "execution_price": frame(prices),
            "valuation_price": frame(prices),
            "universe": frame([True] * len(dates)),
            "observed": frame([offset > 0 for offset in range(len(dates))]),
            "tradable": frame(tradable),
            "shortable": frame([offset > 0 for offset in range(len(dates))]),
            "volume": frame(volumes),
            "initial_cash": initial_cash,
            "active_booksize": active_booksize,
            "inventory_retention": inventory_retention,
            "per_name_short_cap": per_name_short_cap,
        },
    }


def _row(table: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    rows = table.loc[pd.to_datetime(table["trade_date"]).eq(date)]
    assert len(rows) == 1
    return rows.iloc[0]


def test_nav_neutral_endowment_actual_sell_and_quantity_identity() -> None:
    setup = _inputs()
    result = run_signed_execution(**setup["kwargs"])
    first_short = _row(result.signed_positions, setup["dates"][1])
    assert first_short["held_quantity"] == -20
    assert first_short["baseline_quantity"] == 30
    assert first_short["composite_quantity"] == 10
    order = _row(result.orders, setup["dates"][1])
    assert order["direction"] == "sell"
    assert order["requested_quantity"] == 20
    event = _row(result.capitalization_events, setup["dates"][1])
    assert event["cash_change"] + event["quantity"] * event["execution_price"] == pytest.approx(0)
    assert result.reconciliation["quantity_identity_max_error"] == pytest.approx(0)
    assert result.reconciliation["minimum_composite_quantity"] >= 0
    assert result.reconciliation["capitalization_nav_max_error"] == pytest.approx(0)
    assert result.mode == "matched_capitalization"
    assert result.evidence["compatibility_hack"] is True
    assert any("No native borrow" in item for item in result.compatibility_limitations)


def test_signed_partial_fill_advances_only_by_qlib_dealt_quantity() -> None:
    setup = _inputs(volumes=(1_000.0, 5.0, 1_000.0, 1_000.0))
    result = run_signed_execution(**setup["kwargs"])
    position = _row(result.signed_positions, setup["dates"][1])
    fill = _row(result.fills, setup["dates"][1])
    assert fill["filled_quantity"] == 5
    assert fill["reason_code"] == "volume_limited"
    assert position["held_quantity"] == -5
    assert position["composite_quantity"] - position["baseline_quantity"] == -5
    assert result.evidence["signed_quantity_source"].startswith("qlib_composite_dealt")


def test_blocked_cover_retains_needed_baseline_and_releases_after_fill() -> None:
    setup = _inputs(
        intents=(0.0, -0.2, 0.0, 0.0),
        tradable=(True, True, False, True),
        inventory_retention="active_short_only",
    )
    result = run_signed_execution(**setup["kwargs"])
    blocked = _row(result.signed_positions, setup["dates"][2])
    assert blocked["held_quantity"] == -20
    assert blocked["baseline_quantity"] >= 20
    blocked_fill = _row(result.fills, setup["dates"][2])
    assert blocked_fill["filled_quantity"] == 0
    assert blocked_fill["reason_code"] == "buy_blocked"
    covered = _row(result.signed_positions, setup["dates"][3])
    assert covered["held_quantity"] == 0
    assert covered["baseline_quantity"] == 0
    releases = result.capitalization_events.query("event_type == 'release'")
    assert pd.to_datetime(releases["trade_date"]).max() == setup["dates"][3]


def test_insufficient_reserve_and_negative_composite_fail_explicitly() -> None:
    insufficient = _inputs(initial_cash=1_100.0)
    with pytest.raises(ValueError, match="funding reserve is insufficient"):
        run_signed_execution(**insufficient["kwargs"])

    negative = _inputs(per_name_short_cap=0.1)
    with pytest.raises(ValueError, match="capacity is below signed target"):
        run_signed_execution(**negative["kwargs"])


def test_active_performance_uses_active_denominator_and_reconciles_accounts() -> None:
    setup = _inputs(prices=(10.0, 10.0, 8.0, 8.0), initial_cash=3_000.0)
    result = run_signed_execution(**setup["kwargs"])
    active = result.active_account.iloc[2]
    composite = result.composite_account.iloc[2]
    baseline = result.baseline_account.iloc[2]
    assert active["return_denominator"] == pytest.approx(1_000.0)
    assert active["portfolio_return"] == pytest.approx(active["money_pnl"] / 1_000.0)
    assert composite["nav"] == pytest.approx(active["nav"] + baseline["nav"])
    assert result.reconciliation["account_nav_max_error"] == pytest.approx(0)


def test_signed_checkpoint_resume_matches_uninterrupted_observables() -> None:
    setup = _inputs(
        intents=(0.0, -0.2, -0.2, 0.0, -0.2, 0.0),
        prices=(10.0,) * 6,
        volumes=(1_000.0,) * 6,
        tradable=(True,) * 6,
    )
    full = run_signed_execution(**setup["kwargs"])
    prefix = run_signed_execution(**setup["kwargs"], end_position=3)
    suffix = run_signed_execution(
        **setup["kwargs"],
        start_position=3,
        resume_state=prefix.checkpoint,
    )
    for name in (
        "orders",
        "fills",
        "signed_positions",
        "composite_account",
        "baseline_account",
        "active_account",
        "capitalization_events",
    ):
        actual = pd.concat([getattr(prefix, name), getattr(suffix, name)]).reset_index(drop=True)
        expected = getattr(full, name).reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected)
