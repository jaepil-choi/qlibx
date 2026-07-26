from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qlib_extended.research import (
    AsymmetricCostContract,
    ForwardFreeze,
    WalkForwardScheme,
    cross_member_targets,
    evaluate_walk_forward_returns,
    rank_walk_forward_candidates,
)


ROOT = Path(__file__).resolve().parents[1]


def _scheme() -> WalkForwardScheme:
    return WalkForwardScheme.from_yaml(ROOT / "configs" / "splits.yaml")


def _costs() -> AsymmetricCostContract:
    return AsymmetricCostContract.from_yaml(ROOT / "configs" / "costs.yaml")


def test_walk_forward_uses_annual_folds_with_trading_day_purge_and_embargo() -> None:
    calendar = pd.bdate_range("2018-01-02", "2026-07-20")

    folds = _scheme().folds(calendar)

    assert [fold.validation_year for fold in folds] == list(range(2021, 2027))
    first = folds[0]
    pre_validation = calendar[calendar < first.validation_start]
    post_validation = calendar[calendar > first.validation_end]
    assert first.train_end == pre_validation[-64]
    assert first.embargo_end == post_validation[62]
    assert first.segment == "walk_forward_2021"


def test_walk_forward_metrics_keep_full_history_reporting_separate() -> None:
    returns = pd.Series(
        0.0001,
        index=pd.bdate_range("2018-01-02", "2026-07-20"),
    )

    metrics = evaluate_walk_forward_returns(
        returns,
        _scheme(),
        metric_prefix="net_excess",
    )

    segments = {metric.segment for metric in metrics}
    assert "historical_full" in segments
    assert "walk_forward_2021" in segments
    assert all(
        metric.metric.startswith("net_excess_") for metric in metrics
    )


def test_candidate_ranking_ignores_historical_full_metrics() -> None:
    rows: list[dict[str, object]] = []
    for candidate, fold_value, full_value in (
        ("stable", 0.01, -99.0),
        ("unstable", -0.01, 99.0),
    ):
        for year in range(2021, 2027):
            rows.append(
                {
                    "candidate": candidate,
                    "segment": f"walk_forward_{year}",
                    "metric": "net_excess_annual_return",
                    "value": fold_value,
                }
            )
        rows.append(
            {
                "candidate": candidate,
                "segment": "historical_full",
                "metric": "net_excess_annual_return",
                "value": full_value,
            }
        )

    ranking = rank_walk_forward_candidates(
        pd.DataFrame(rows),
        _scheme(),
        metric="net_excess_annual_return",
    )

    assert ranking["candidate"].tolist() == ["stable", "unstable"]
    assert ranking.loc[0, "selection_score"] == pytest.approx(0.01)


def test_candidate_ranking_rejects_a_candidate_with_missing_fold() -> None:
    rows = [
        {
            "candidate": candidate,
            "segment": f"walk_forward_{year}",
            "metric": "score",
            "value": 0.01,
        }
        for candidate in ("complete", "incomplete")
        for year in range(2021, 2027)
        if not (candidate == "incomplete" and year == 2024)
    ]

    with pytest.raises(ValueError, match="missing walk-forward folds"):
        rank_walk_forward_candidates(pd.DataFrame(rows), _scheme(), metric="score")


def test_forward_oos_label_requires_complete_freeze_and_post_freeze_date() -> None:
    complete = ForwardFreeze(
        definition_frozen=True,
        data_config_frozen=True,
        family_membership_frozen=True,
        sizing_frozen=True,
        forward_eligible_from=pd.Timestamp("2026-07-21"),
    )
    incomplete = ForwardFreeze(
        definition_frozen=True,
        data_config_frozen=True,
        family_membership_frozen=False,
        sizing_frozen=True,
        forward_eligible_from=pd.Timestamp("2026-07-21"),
    )

    assert complete.segment_for(pd.Timestamp("2026-07-20")) == "historical_research"
    assert complete.segment_for(pd.Timestamp("2026-07-21")) == "forward_oos"
    assert incomplete.segment_for(pd.Timestamp("2027-01-01")) == "historical_research"


def test_cost_is_charged_once_after_member_crossing() -> None:
    date = pd.DatetimeIndex(["2026-01-02"])
    columns = ["A"]
    member_targets = {
        "long": pd.DataFrame([[0.10]], index=date, columns=columns),
        "short": pd.DataFrame([[-0.08]], index=date, columns=columns),
    }
    crossed = cross_member_targets(member_targets, {"long": 1.0, "short": 1.0})

    result = _costs().evaluate_netted_orders(
        stock_target=crossed,
        stock_pretrade=pd.DataFrame([[0.0]], index=date, columns=columns),
        etf_target=pd.Series([0.0], index=date),
        etf_pretrade=pd.Series([0.0], index=date),
    )

    assert crossed.iloc[0, 0] == pytest.approx(0.02)
    assert result.loc[date[0], "stock_buy_turnover"] == pytest.approx(0.02)
    assert result.loc[date[0], "total_trade_cost"] == pytest.approx(0.02 * 0.0003)


def test_stock_sell_uses_23_bps_and_financing_unwind_is_explicit() -> None:
    date = pd.DatetimeIndex(["2026-01-02"])
    columns = ["A", "B"]
    result = _costs().evaluate_netted_orders(
        stock_target=pd.DataFrame([[0.05, 0.0]], index=date, columns=columns),
        stock_pretrade=pd.DataFrame([[0.0, 0.04]], index=date, columns=columns),
        etf_target=pd.Series([0.95], index=date),
        etf_pretrade=pd.Series([1.0], index=date),
        financed_notional=pd.Series([0.05], index=date),
        expected_unwind_fraction=0.5,
    )

    expected = 0.05 * 0.0003 + 0.04 * 0.0023 + 0.05 * 0.0003
    expected += 0.05 * 0.5 * (0.0023 + 0.0003)
    assert result.loc[date[0], "total_trade_cost"] == pytest.approx(expected)


def test_cost_contract_rejects_unfunded_financing_and_axis_mismatch() -> None:
    date = pd.DatetimeIndex(["2026-01-02"])
    stock_target = pd.DataFrame([[0.02]], index=date, columns=["A"])
    stock_pretrade = pd.DataFrame([[0.0]], index=date, columns=["A"])

    with pytest.raises(ValueError, match="exceeds same-day"):
        _costs().evaluate_netted_orders(
            stock_target=stock_target,
            stock_pretrade=stock_pretrade,
            etf_target=pd.Series([0.99], index=date),
            etf_pretrade=pd.Series([1.0], index=date),
            financed_notional=pd.Series([0.02], index=date),
        )

    with pytest.raises(ValueError, match="Axis mismatch"):
        cross_member_targets(
            {
                "left": stock_target,
                "right": pd.DataFrame([[0.02]], index=date, columns=["B"]),
            },
            {"left": 0.5, "right": 0.5},
        )


def test_financed_inventory_charges_amortized_23bp_stock_unwind() -> None:
    dates = pd.DatetimeIndex(["2026-01-02", "2026-01-05"])
    inventory = pd.Series([0.20, 0.10], index=dates)

    cost = _costs().expected_inventory_unwind_cost(
        inventory,
        unwind_horizon_days=63,
    )

    assert cost.iloc[0] == pytest.approx(0.20 * (0.0023 + 0.0003) / 63)
    assert cost.iloc[1] == pytest.approx(0.10 * (0.0023 + 0.0003) / 63)
