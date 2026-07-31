"""Carry SERIES builder — Step 2a of the carry catalog/engine refactor.

The 5 carry indicators are scalar (one curve snapshot -> one value). For the
backtest pipeline they must exist as per-DATE columns in strategy_indicators.csv.
``build_carry_indicator_frame`` is the vectorized series builder: it reads the
on-disk forward curve (``sort_by_date.csv``) once, date-major, and emits the 5
carry indicators + their settlement/dte byproducts as a date-indexed frame.

It is a behavior-preserving port of qorka's ``lib/data/carry_basis.py::
build_carry_basis_series`` (verbatim weekday-approx expiry), spelled to echolon's
NO_ERROR_HANDLING policy (regex pre-filter instead of try/except; no ``.get``
defaults). Degenerate days -> NaN is a DELIBERATE domain sentinel for a series
builder (the scalar calcs raise; a series builder cannot let one bad day kill the
whole backtest).

These tests are hermetic + HAND-COMPUTED — expecteds are derived from the spec
formula, never pasted from qorka's output (a pasted expected only guards
transcription, not the formula).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from echolon.indicators.calculators.interday.carry import carry_front_back
from echolon.indicators.calculators.interday.carry.series_builder import (
    CARRY_INDICATOR_COLUMNS,
    _carry_front_back,
    _curve_slope_near,
    build_carry_indicator_frame,
)


# --------------------------------------------------------------------------- #
# Synthetic on-disk forward curve
# --------------------------------------------------------------------------- #
def _write_sbd(dir_path, instrument: str, rows: list[tuple], market: str = "SHFE") -> None:
    """Write a synthetic sort_by_date.csv at the echolon-native layout
    ``{dir_path}/{MARKET}/{instrument}/sort_by_date.csv``.
    rows = (date_int, contract, settle, oi)."""
    inst_dir = dir_path / market.upper() / instrument
    inst_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["date", "contract", "settlement", "open_interest"])
    df.to_csv(inst_dir / "sort_by_date.csv", index=False)


def _three_contract_rows(n_dates: int = 80, degenerate_at: int | None = None) -> list[tuple]:
    """n_dates business days, 3 non-expiring active contracts (al2406/07/08).

    Settlements vary deterministically so front returns + carry are non-constant
    (vol/sigma > floor -> risk_adj_carry / carry_z_3m are finite after warmup).
    If ``degenerate_at`` is set, that date index carries only ONE contract.
    """
    dates = pd.bdate_range("2024-01-02", periods=n_dates)
    rows: list[tuple] = []
    for i, d in enumerate(dates):
        di = int(d.strftime("%Y%m%d"))
        front = 100.0 + 0.5 * np.sin(i / 5.0)
        back = 110.0 + 0.3 * np.cos(i / 7.0)
        third = 115.0 + 0.2 * np.sin(i / 9.0)
        if degenerate_at is not None and i == degenerate_at:
            rows.append((di, "al2406", front, 1000))
            continue
        rows.append((di, "al2406", front, 1000))
        rows.append((di, "al2407", back, 900))
        rows.append((di, "al2408", third, 800))
    return rows


# --------------------------------------------------------------------------- #
# 1. Hand-computed formula units (the load-bearing tests)
# --------------------------------------------------------------------------- #
def test_carry_front_back_formula_hand_computed():
    # (settle_front/settle_back - 1) * 365 / (dte_back - dte_front)
    # = (100/110 - 1) * 365 / 30 = -0.0909090909 * 365 / 30 = -1.10606060...
    got = _carry_front_back(100.0, 110.0, 10, 40)
    assert got == pytest.approx(-1.1060606060606, abs=1e-10)
    # independent re-derivation from the spec expression
    assert got == pytest.approx((100.0 / 110.0 - 1.0) * 365.0 / 30.0)


def test_carry_front_back_zero_dte_spread_is_nan():
    # dte_back == dte_front -> cannot annualize -> NaN sentinel (not raise)
    assert np.isnan(_carry_front_back(100.0, 110.0, 30, 30))


def test_curve_slope_near_hand_computed():
    # Construct log(settlement) EXACTLY linear in dte with slope -0.002.
    # curve_slope_near returns -slope = +0.002 (positive = backwardation).
    dtes = np.array([10.0, 40.0, 70.0])
    settles = np.exp(5.0 + (-0.002) * dtes)
    assert _curve_slope_near(settles, dtes) == pytest.approx(0.002, rel=1e-9)


def test_curve_slope_near_nonpositive_settle_is_nan():
    assert np.isnan(_curve_slope_near(np.array([100.0, -5.0]), np.array([10.0, 40.0])))


def test_scalar_equivalence_with_echelon_carry_front_back():
    # Vectorized helper must equal echolon's canonical SCALAR carry_front_back
    # on the same 2-contract snapshot.
    snap = pd.DataFrame({"settlement": [100.0, 110.0], "days_to_expiry": [10, 40]})
    assert _carry_front_back(100.0, 110.0, 10, 40) == pytest.approx(carry_front_back(snap))


# --------------------------------------------------------------------------- #
# 2. Integration + internal consistency on a synthetic forward curve
# --------------------------------------------------------------------------- #
def test_build_frame_has_carry_columns_and_date_index(tmp_path):
    _write_sbd(tmp_path, "al", _three_contract_rows())
    out = build_carry_indicator_frame("al", market_data_dir=tmp_path)
    assert isinstance(out.index, pd.DatetimeIndex)
    for col in CARRY_INDICATOR_COLUMNS:
        assert col in out.columns, f"{col} missing from builder output"
    # the 5 canonical names
    assert set(CARRY_INDICATOR_COLUMNS) == {
        "carry_front_back", "curve_slope_near", "risk_adj_carry",
        "carry_z_3m", "carry_change_20d",
    }


def test_carry_front_back_column_internally_consistent(tmp_path):
    # The vectorized carry column must equal the scalar formula applied to the
    # builder's OWN settlement/dte byproduct columns — proves the vectorization
    # wired the right columns into the right formula (no hand-computed calendar
    # needed).
    _write_sbd(tmp_path, "al", _three_contract_rows())
    out = build_carry_indicator_frame("al", market_data_dir=tmp_path)
    valid = out.dropna(subset=["settlement_front", "settlement_back"])
    assert len(valid) > 10
    for d, row in valid.iterrows():
        expected = _carry_front_back(
            row["settlement_front"], row["settlement_back"],
            int(row["days_to_expiry_front"]), int(row["days_to_expiry_back"]),
        )
        assert row["carry_front_back"] == pytest.approx(expected, nan_ok=True)


def test_rolling_derivatives_match_their_defining_relations(tmp_path):
    _write_sbd(tmp_path, "al", _three_contract_rows())
    out = build_carry_indicator_frame("al", market_data_dir=tmp_path)
    cfb = out["carry_front_back"]
    # carry_change_20d == carry_today - carry_(t-20), incl NaN propagation
    pd.testing.assert_series_equal(
        out["carry_change_20d"], (cfb - cfb.shift(20)).rename("carry_change_20d"),
        check_names=False,
    )
    # carry_z_3m == (carry - rolling_mean63) / rolling_std63(ddof=1) after floor
    mu = cfb.rolling(63).mean()
    sigma = cfb.rolling(63).std(ddof=1).where(lambda s: s > 1e-12)
    pd.testing.assert_series_equal(
        out["carry_z_3m"], ((cfb - mu) / sigma).rename("carry_z_3m"), check_names=False,
    )
    # at least some finite z-scores exist past the 63-day warmup
    assert out["carry_z_3m"].notna().sum() > 0


# --------------------------------------------------------------------------- #
# 3. Degenerate day -> NaN sentinel + propagation (plan risk #2)
# --------------------------------------------------------------------------- #
def test_degenerate_day_is_nan_and_does_not_raise(tmp_path):
    rows = _three_contract_rows(n_dates=30, degenerate_at=12)
    _write_sbd(tmp_path, "al", rows)
    out = build_carry_indicator_frame("al", market_data_dir=tmp_path)  # must not raise
    deg_date = pd.Timestamp(pd.bdate_range("2024-01-02", periods=30)[12])
    assert np.isnan(out.loc[deg_date, "carry_front_back"])
    assert np.isnan(out.loc[deg_date, "settlement_front"])
    # the NaN at the degenerate date propagates into the 20-day change exactly
    cfb = out["carry_front_back"]
    pd.testing.assert_series_equal(
        out["carry_change_20d"], (cfb - cfb.shift(20)).rename("carry_change_20d"),
        check_names=False,
    )


def test_unparseable_contracts_are_dropped_no_raise(tmp_path):
    # A junk contract code must be filtered without try/except blowing up; the
    # valid two-contract basis on that date still computes.
    rows = [
        (20240102, "al2406", 100.0, 1000),
        (20240102, "al2407", 110.0, 900),
        (20240102, "GARBAGE", 999.0, 1),
    ]
    _write_sbd(tmp_path, "al", rows)
    out = build_carry_indicator_frame("al", market_data_dir=tmp_path)
    d = pd.Timestamp("2024-01-02")
    assert not np.isnan(out.loc[d, "carry_front_back"])


def test_back_open_interest_is_back_contract_oi(tmp_path):
    # echolon emits back_open_interest (the back contract's OI) as a supporting
    # column — the R&D basis back-leg-liquidity input. In the synthetic curve the
    # back contract is al2407 (OI=900) on every non-degenerate date.
    _write_sbd(tmp_path, "al", _three_contract_rows(n_dates=10))
    out = build_carry_indicator_frame("al", market_data_dir=tmp_path)
    assert "back_open_interest" in out.columns
    valid = out["back_open_interest"].dropna()
    assert len(valid) > 0
    assert (valid == 900).all()


# --------------------------------------------------------------------------- #
# 4. Real-data parity regression (committed fixture — exercises a real roll)
# --------------------------------------------------------------------------- #
def test_real_aluminum_slice_parity_regression():
    """A 150-date slice of real SHFE aluminum (~12 active contracts, spanning
    front-contract ROLLS the fixed-3-contract synthetic test can't reach). The
    expected output was generated from this builder AND verified byte-equal to
    qorka's build_carry_basis_series on the same slice — pins the load-bearing
    parity as a permanent guard, not a once-and-walk-away check."""
    from pathlib import Path

    fx = Path(__file__).parent / "fixtures"
    out = build_carry_indicator_frame("al", market_data_dir=fx / "carry_slice")
    expected = pd.read_csv(
        fx / "carry_aluminum_slice_expected.csv", index_col=0, parse_dates=[0]
    )
    out = out[list(expected.columns)]
    pd.testing.assert_frame_equal(
        out, expected, check_dtype=False, check_exact=False, rtol=1e-9, atol=1e-12,
        check_names=False,
    )
