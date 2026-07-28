from __future__ import annotations

import pandas as pd
import pytest

from qlibx.alpha import analyze_exposure, apply_transform


def test_builtin_operation_has_versioned_deterministic_lineage() -> None:
    dates = pd.date_range("2025-01-01", periods=3)
    values = pd.DataFrame(
        [[1.0, 3.0], [2.0, 6.0], [4.0, 8.0]],
        index=dates,
        columns=["A", "B"],
    )
    first = apply_transform("linear_decay", values, window=2)
    second = apply_transform("linear_decay", values, window=2)
    pd.testing.assert_frame_equal(first.values, second.values)
    assert first.lineage == second.lineage
    assert first.lineage[0].operation_id == "qlibx.alpha.linear_decay"
    assert first.lineage[0].version == "1"
    assert first.lineage[0].minimum_observations == 2
    assert first.lineage[0].nan_behavior == "full_window_required"


def test_group_demean_records_missing_group_and_neutrality_warning() -> None:
    date = pd.Timestamp("2025-01-01")
    values = pd.DataFrame([[1.0, 3.0, 9.0]], index=[date], columns=["A", "B", "C"])
    groups = pd.DataFrame([["x", "x", pd.NA]], index=[date], columns=values.columns)
    result = apply_transform("group_demean", values, groups=groups)
    assert result.values.loc[date, "A"] == pytest.approx(-1.0)
    assert pd.isna(result.values.loc[date, "C"])
    assert result.lineage[0].group_missing_behavior == "missing_group_produces_missing_output"
    assert "not proof" in result.neutrality_warning


def test_exposure_artifact_records_method_data_window_coverage_and_missingness() -> None:
    dates = pd.date_range("2025-01-01", periods=2)
    weights = pd.DataFrame(
        [[0.4, -0.2, pd.NA], [0.3, -0.1, 0.2]],
        index=dates,
        columns=["A", "B", "C"],
        dtype="Float64",
    )
    beta = pd.DataFrame(1.0, index=dates, columns=weights.columns)
    groups = pd.DataFrame(
        [["tech", "finance", "tech"], ["tech", "finance", "tech"]],
        index=dates,
        columns=weights.columns,
    )
    realized = weights.fillna(0.0) * 0.5
    artifact = analyze_exposure(
        weights,
        input_id="alpha-run-1",
        dataset_ids={"market_beta": "beta-v2", "sector": "sector-pit-v1"},
        method="weighted_sum",
        market_beta=beta,
        benchmark_beta=beta * 0.8,
        groups=groups,
        factors={"value": beta * 0.5},
        realized_holdings=realized,
    )
    assert artifact.analyzer_id == "qlibx.alpha.exposure"
    assert artifact.analyzer_version == "1"
    assert artifact.method == "weighted_sum"
    assert artifact.dataset_ids["sector"] == "sector-pit-v1"
    assert artifact.estimation_window == (str(dates[0]), str(dates[-1]))
    assert artifact.coverage.iloc[0] == 2
    assert artifact.missingness.iloc[0] == pytest.approx(1 / 3)
    assert artifact.market_exposure.iloc[0] == pytest.approx(0.2)
    assert artifact.group_exposure.loc[dates[0], "finance"] == pytest.approx(-0.2)
    assert artifact.factor_exposure.loc[dates[1], "value"] == pytest.approx(0.2)
    assert artifact.intended_realized_gap is not None
    assert "not proof" in artifact.neutrality_warning
