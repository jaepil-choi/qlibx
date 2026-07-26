from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qlib_extended.research.crossing import (
    compute_crossing_diagnostics,
    compute_pairwise_diagnostics,
)


def weight(values: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(
        values,
        index=pd.date_range("2024-01-02", periods=len(values), freq="B"),
        columns=["A", "B"],
        dtype="float64",
    )


def test_pairwise_opposite_positions_measure_netting_and_trade_crossing() -> None:
    left = weight([[1.0, -1.0], [0.0, 0.0]])
    right = weight([[-1.0, 1.0], [0.0, 0.0]])
    realized = weight([[0.01, -0.01], [0.0, 0.0]])

    result = compute_pairwise_diagnostics(
        left,
        right,
        left_name="left",
        right_name="right",
        realized_return=realized,
    )

    first = result.daily.iloc[0]
    assert first["naive_position_gross"] == pytest.approx(2.0)
    assert first["combined_position_gross"] == pytest.approx(0.0)
    assert first["position_netting_rate"] == pytest.approx(1.0)
    assert first["naive_trade_gross"] == pytest.approx(2.0)
    assert first["combined_trade_gross"] == pytest.approx(0.0)
    assert first["internal_crossing_notional"] == pytest.approx(1.0)
    assert first["cross_sectional_weight_corr"] == pytest.approx(-1.0)
    assert first["cross_sectional_weight_cosine"] == pytest.approx(-1.0)
    assert first["opposite_position_overlap"] == pytest.approx(2.0)
    assert result.summary["return_correlation"] == pytest.approx(-1.0)


def test_multi_member_crossing_uses_target_deltas_not_position_overlap() -> None:
    left = weight([[0.5, -0.5], [1.0, -1.0]])
    right = weight([[0.5, -0.5], [0.0, 0.0]])

    realized = weight([[0.01, -0.01], [0.02, -0.02]])
    result = compute_crossing_diagnostics(
        {"left": left, "right": right},
        realized_return=realized,
    )

    second = result.daily.iloc[1]
    assert second["position_netting_saving_gross"] == pytest.approx(0.0)
    assert second["naive_trade_gross"] == pytest.approx(1.0)
    assert second["combined_trade_gross"] == pytest.approx(0.0)
    assert second["trade_crossing_rate"] == pytest.approx(1.0)
    assert second["combined_gross_return"] == pytest.approx(0.02)
    assert second["combined_net_return"] == pytest.approx(0.02)
    assert "net_sharpe" in result.summary


def test_weight_axis_mismatch_fails_explicitly() -> None:
    left = weight([[1.0, -1.0]])
    right = left.rename(columns={"B": "C"})

    with pytest.raises(ValueError, match="exact same ticker columns"):
        compute_crossing_diagnostics({"left": left, "right": right})


def test_non_finite_weight_fails_explicitly() -> None:
    left = weight([[np.nan, 0.0]])
    right = weight([[0.0, 0.0]])

    with pytest.raises(ValueError, match="non-finite"):
        compute_crossing_diagnostics({"left": left, "right": right})
