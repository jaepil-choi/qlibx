"""
Tests for the 5 carry indicators (Gate 1C WS2 B2.3).

All tests are SYNTHETIC (real market data not available on dev machine).
Each indicator gets:
- A deterministic correctness test on a hand-crafted curve fixture.
- A sign-convention test (positive ↔ backwardation, negative ↔ contango).
- An edge-case test (degenerate input → fail-loud).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from echolon.indicators.calculators.interday.carry import (
    carry_change_20d,
    carry_front_back,
    carry_z_3m,
    curve_slope_near,
    risk_adj_carry,
)


# ---------------------------------------------------------------------------
# Synthetic curve helpers
# ---------------------------------------------------------------------------


def _backwardation_curve() -> pd.DataFrame:
    """Front > back ⇒ backwardation ⇒ qorka sign = positive (long)."""
    return pd.DataFrame({
        "contract": ["zn2407", "zn2408", "zn2409"],
        "settlement": [22200.0, 22100.0, 22000.0],
        "days_to_expiry": [25, 56, 84],
        "expiry_date": pd.to_datetime(["2024-06-28", "2024-07-31", "2024-08-30"]),
    })


def _contango_curve() -> pd.DataFrame:
    """Front < back ⇒ contango ⇒ qorka sign = negative (short)."""
    return pd.DataFrame({
        "contract": ["zn2407", "zn2408", "zn2409"],
        "settlement": [22000.0, 22100.0, 22200.0],
        "days_to_expiry": [25, 56, 84],
        "expiry_date": pd.to_datetime(["2024-06-28", "2024-07-31", "2024-08-30"]),
    })


# ---------------------------------------------------------------------------
# carry_front_back
# ---------------------------------------------------------------------------


def test_carry_front_back_backwardation_is_positive():
    """Sign convention: front > back → positive."""
    out = carry_front_back(_backwardation_curve())
    assert out > 0


def test_carry_front_back_contango_is_negative():
    out = carry_front_back(_contango_curve())
    assert out < 0


def test_carry_front_back_value_matches_formula():
    """Verify against the docstring formula:
        annualized = (settlement_front/settlement_back - 1) * 365 / dte_diff
    """
    curve = _backwardation_curve()
    expected = (22200.0 / 22100.0 - 1.0) * 365.0 / (56 - 25)
    assert math.isclose(carry_front_back(curve), expected, rel_tol=1e-12)


def test_carry_front_back_too_few_contracts_raises():
    curve = pd.DataFrame({"settlement": [22100.0], "days_to_expiry": [25]})
    with pytest.raises(ValueError):
        carry_front_back(curve)


def test_carry_front_back_equal_dtes_raises():
    """Degenerate two-contract case (same DTE) is fail-loud."""
    curve = pd.DataFrame({
        "settlement": [22100.0, 22150.0],
        "days_to_expiry": [25, 25],
    })
    with pytest.raises(ValueError, match="zero expiry-spread"):
        carry_front_back(curve)


# ---------------------------------------------------------------------------
# curve_slope_near
# ---------------------------------------------------------------------------


def test_curve_slope_near_backwardation_is_positive():
    """Slope of log(settlement) vs DTE is negative in backwardation
    (settlement falls as DTE grows); the indicator returns -slope so
    backwardation → positive."""
    out = curve_slope_near(_backwardation_curve())
    assert out > 0


def test_curve_slope_near_contango_is_negative():
    out = curve_slope_near(_contango_curve())
    assert out < 0


def test_curve_slope_near_value_matches_polyfit():
    curve = _backwardation_curve()
    settlements = curve["settlement"].head(3).values
    dtes = curve["days_to_expiry"].head(3).values
    expected_slope, _ = np.polyfit(dtes, np.log(settlements), 1)
    assert math.isclose(curve_slope_near(curve), -expected_slope, rel_tol=1e-12)


def test_curve_slope_near_uses_n_contracts(monkeypatch):
    """If n=2, only the first 2 rows participate."""
    curve = _backwardation_curve()
    val_n2 = curve_slope_near(curve, n=2)
    val_n3 = curve_slope_near(curve, n=3)
    # Different sample → different value (won't be equal in general).
    assert not math.isclose(val_n2, val_n3, rel_tol=1e-9)


def test_curve_slope_near_too_few_contracts_raises():
    curve = pd.DataFrame({"settlement": [22100.0], "days_to_expiry": [25]})
    with pytest.raises(ValueError):
        curve_slope_near(curve)


def test_curve_slope_near_non_positive_settlement_raises():
    curve = pd.DataFrame({
        "settlement": [22100.0, -50.0, 22200.0],
        "days_to_expiry": [25, 56, 84],
    })
    with pytest.raises(ValueError, match="non-positive"):
        curve_slope_near(curve)


# ---------------------------------------------------------------------------
# risk_adj_carry
# ---------------------------------------------------------------------------


def test_risk_adj_carry_divides_carry_by_vol():
    """The indicator should equal carry_front_back / realized_vol."""
    curve = _backwardation_curve()
    # 30-day series of front-contract settlements with simple +0.5%
    # daily drift then mild noise → controlled vol.
    rng = np.random.default_rng(seed=42)
    base = 22000.0
    series = pd.Series(
        base + np.cumsum(rng.normal(loc=0.0, scale=10.0, size=30))
    )
    raw_carry = carry_front_back(curve)
    expected_vol = series.pct_change().dropna().tail(20).std(ddof=1)
    out = risk_adj_carry(curve, series, window=20)
    assert math.isclose(out, raw_carry / float(expected_vol), rel_tol=1e-9)


def test_risk_adj_carry_preserves_sign():
    rng = np.random.default_rng(seed=7)
    series = pd.Series(22000.0 + np.cumsum(rng.normal(0, 5, size=30)))
    assert risk_adj_carry(_backwardation_curve(), series, window=20) > 0
    assert risk_adj_carry(_contango_curve(), series, window=20) < 0


def test_risk_adj_carry_short_history_raises():
    short_series = pd.Series([22000.0, 22010.0, 22005.0])
    with pytest.raises(ValueError, match="need >="):
        risk_adj_carry(_backwardation_curve(), short_series, window=20)


def test_risk_adj_carry_constant_history_raises():
    flat = pd.Series([22000.0] * 30)
    with pytest.raises(ValueError, match="constant"):
        risk_adj_carry(_backwardation_curve(), flat, window=20)


# ---------------------------------------------------------------------------
# carry_z_3m
# ---------------------------------------------------------------------------


def test_carry_z_3m_zero_for_carry_at_mean():
    """If today's carry equals the rolling mean → z = 0."""
    series = pd.Series([0.05, 0.06, 0.04] * 21 + [0.05])  # mean ≈ 0.05
    z = carry_z_3m(series, window=63)
    assert math.isclose(z, 0.0, abs_tol=0.001)


def test_carry_z_3m_positive_when_today_above_mean():
    series = pd.Series([0.05, 0.06, 0.04] * 21 + [0.20])
    assert carry_z_3m(series, window=63) > 0


def test_carry_z_3m_negative_when_today_below_mean():
    series = pd.Series([0.05, 0.06, 0.04] * 21 + [-0.10])
    assert carry_z_3m(series, window=63) < 0


def test_carry_z_3m_constant_history_raises():
    flat = pd.Series([0.05] * 63)
    with pytest.raises(ValueError, match="constant"):
        carry_z_3m(flat, window=63)


def test_carry_z_3m_short_history_raises():
    with pytest.raises(ValueError, match="need >="):
        carry_z_3m(pd.Series([0.05] * 10), window=63)


# ---------------------------------------------------------------------------
# carry_change_20d
# ---------------------------------------------------------------------------


def test_carry_change_20d_today_minus_past():
    # 21 entries: indices 0..20; lag=20 → past = idx 0, today = idx 20
    series = pd.Series([0.02, 0.025] + [0.03] * 18 + [0.05])
    out = carry_change_20d(series, lag=20)
    assert math.isclose(out, 0.05 - 0.02, rel_tol=1e-12)


def test_carry_change_20d_positive_when_carry_rose():
    series = pd.Series(list(np.linspace(0.01, 0.05, 21)))
    out = carry_change_20d(series, lag=20)
    assert out > 0


def test_carry_change_20d_negative_when_carry_fell():
    series = pd.Series(list(np.linspace(0.05, 0.01, 21)))
    out = carry_change_20d(series, lag=20)
    assert out < 0


def test_carry_change_20d_too_short_raises():
    with pytest.raises(ValueError, match="need >="):
        carry_change_20d(pd.Series([0.05, 0.06]), lag=20)


# ---------------------------------------------------------------------------
# Cross-cutting: name match between echolon and qorka
# ---------------------------------------------------------------------------


def test_all_5_indicator_names_match_qorka_pool():
    """The 5 echolon-side names MUST match qorka's pool registration
    byte-equal. Failure here means the cross-repo wiring is broken."""
    from echolon.indicators.calculators.interday import carry as carry_pkg

    expected = {
        "carry_front_back",
        "curve_slope_near",
        "risk_adj_carry",
        "carry_z_3m",
        "carry_change_20d",
    }
    for name in expected:
        assert hasattr(carry_pkg, name), (
            f"echolon carry pkg missing '{name}' — qorka "
            f"paradigms/carry/indicator_pool.py expects this exact name"
        )
        assert callable(getattr(carry_pkg, name))
