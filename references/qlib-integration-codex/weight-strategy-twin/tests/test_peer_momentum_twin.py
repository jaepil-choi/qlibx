from __future__ import annotations

# ruff: noqa: E402

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


INTEGRATION_DIR = Path(__file__).resolve().parents[1]
if str(INTEGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_DIR))

from kwam_qlib.exchange import build_quote_frame
from kwam_qlib.signals import (
    build_long_only_target,
    compute_equal_weight_peer_momentum,
    scale_peer_signal,
)


def test_equal_weight_peer_momentum_is_leave_one_out_group_return() -> None:
    dates = pd.to_datetime(["2024-01-02"])
    columns = pd.Index(["A", "B", "C", "D"])
    returns = pd.DataFrame([[0.10, 0.20, -0.10, 0.30]], index=dates, columns=columns)
    groups = pd.DataFrame([[1, 1, 2, 3]], index=dates, columns=columns)
    universe = pd.DataFrame([[True, True, True, False]], index=dates, columns=columns)

    signal = compute_equal_weight_peer_momentum(returns, groups, universe).iloc[0]

    assert signal["A"] == pytest.approx(0.20)
    assert signal["B"] == pytest.approx(0.10)
    assert pd.isna(signal["C"])
    assert pd.isna(signal["D"])


def test_signal_scaling_matches_full_side_budget_contract() -> None:
    signal = pd.Series({"A": 2.0, "B": 1.0, "C": -3.0, "D": -1.0})
    universe = pd.Series(True, index=signal.index)

    weight = scale_peer_signal(signal, universe)

    assert weight.clip(lower=0.0).sum() == pytest.approx(1.0)
    assert weight.clip(upper=0.0).sum() == pytest.approx(-1.0)
    assert weight["A"] == pytest.approx(2.0 / 3.0)
    assert weight["C"] == pytest.approx(-3.0 / 4.0)


def test_long_only_target_adds_active_tilt_and_normalizes() -> None:
    index = pd.Index(["A", "B", "C"])
    signal = pd.Series([0.20, -0.10, -0.20], index=index)
    benchmark = pd.Series([0.50, 0.30, 0.20], index=index)
    universe = pd.Series(True, index=index)

    target, active = build_long_only_target(
        signal,
        benchmark,
        universe,
        active_multiplier=0.10,
    )

    assert active.sum() == pytest.approx(0.0)
    assert target.sum() == pytest.approx(1.0)
    assert target.ge(0.0).all()
    assert target["A"] > benchmark["A"]
    assert target["C"] < benchmark["C"]


def test_quote_bridge_preserves_complete_matrix_and_qlib_index_order() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    columns = pd.Index(["A", "B"])
    close = pd.DataFrame([[100.0, np.nan], [101.0, 50.0]], index=dates, columns=columns)
    returns = close.pct_change(fill_method=None)
    volume = pd.DataFrame(1000.0, index=dates, columns=columns)

    quote = build_quote_frame(close, returns, volume)

    assert quote.index.names == ["instrument", "datetime"]
    assert len(quote) == 4
    assert pd.isna(quote.loc[("B", dates[0]), "$close"])
    assert quote.loc[("A", dates[1]), "$factor"] == pytest.approx(1.0)
