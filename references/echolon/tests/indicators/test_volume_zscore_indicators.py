"""Tests for the pre-computed, per-contract volume z-score indicators
(``obv_zscore`` / ``ad_zscore``).

These exist so a strategy can read a scale-invariant OBV/AD value as a normal
pre-computed indicator (``get_indicator('obv_zscore')``) instead of computing a
runtime rolling z-score via ``get_indicator_series('obv', N)`` — the fragile
pattern that crashes (IndexError) on a WFA OOS window shorter than the lookback
and silently reads future bars on long windows.

Design note: warmup (first ``period - 1`` bars, insufficient history) -> NaN,
the honest "not yet computable" marker (consumers NaN-guard, as for trix/atr).
A degenerate window with zero dispersion (std == 0) -> 0.0. This differs from
``price_zscore`` (which fills warmup with 0); NaN-on-warmup matches the TA-Lib
lookback convention and the No-Misleading-Fallback policy.
"""
import numpy as np
import pandas as pd
import pytest
import talib

from echolon.indicators.calculators.interday import ta_lib
from echolon.indicators import catalog
from echolon.indicators.registry.utils import get_function


def _df(n=300, seed=0):
    rng = np.random.RandomState(seed)
    close = 15000 + np.cumsum(rng.randn(n) * 50)
    high = close + np.abs(rng.randn(n) * 20)
    low = close - np.abs(rng.randn(n) * 20)
    volume = np.abs(rng.randn(n) * 1000 + 200000)
    return pd.DataFrame({"open": close, "high": high, "low": low,
                         "close": close, "volume": volume})


# --------------------------------------------------------------------------
# obv_zscore — function behavior
# --------------------------------------------------------------------------

def test_obv_zscore_returns_array_of_full_length():
    df = _df(300)
    out = ta_lib.obv_zscore(df, period=20)
    assert isinstance(out, np.ndarray)
    assert len(out) == len(df)


def test_obv_zscore_warmup_bars_are_nan():
    """First ``period - 1`` bars have insufficient history -> NaN (not 0)."""
    period = 30
    df = _df(120)
    out = ta_lib.obv_zscore(df, period=period)
    assert np.all(np.isnan(out[: period - 1])), "warmup bars must be NaN"
    assert not np.isnan(out[period - 1]), "first full-window bar must be finite"


def test_obv_zscore_matches_independent_rolling_zscore():
    """Post-warmup values equal (OBV - rollmean) / rollstd computed independently."""
    period = 25
    df = _df(200, seed=3)
    out = ta_lib.obv_zscore(df, period=period)

    obv = pd.Series(talib.OBV(df["close"].values, df["volume"].values))
    mean = obv.rolling(window=period).mean()
    std = obv.rolling(window=period).std()
    expected = ((obv - mean) / std).to_numpy()

    # compare only the finite (post-warmup, std>0) region
    finite = ~np.isnan(out)
    assert finite.sum() > 50
    np.testing.assert_allclose(out[finite], expected[finite], rtol=1e-9, atol=1e-9)


def test_obv_zscore_zero_dispersion_window_is_zero_not_nan_or_inf():
    """Flat close -> OBV constant -> std==0 over a full window -> z-score 0.0."""
    period = 10
    n = 50
    df = pd.DataFrame({
        "open": [15000.0] * n, "high": [15000.0] * n, "low": [15000.0] * n,
        "close": [15000.0] * n,                      # flat -> OBV constant
        "volume": [200000.0] * n,
    })
    out = ta_lib.obv_zscore(df, period=period)
    tail = out[period - 1:]                           # full-window region
    assert np.all(np.isfinite(tail)), "std==0 must not produce NaN/inf"
    np.testing.assert_allclose(tail, 0.0)


# --------------------------------------------------------------------------
# ad_zscore — function behavior (same family)
# --------------------------------------------------------------------------

def test_ad_zscore_matches_independent_rolling_zscore():
    period = 20
    df = _df(200, seed=7)
    out = ta_lib.ad_zscore(df, period=period)

    ad = pd.Series(talib.AD(df["high"].values, df["low"].values,
                            df["close"].values, df["volume"].values))
    mean = ad.rolling(window=period).mean()
    std = ad.rolling(window=period).std()
    expected = ((ad - mean) / std).to_numpy()

    finite = ~np.isnan(out)
    assert finite.sum() > 50
    np.testing.assert_allclose(out[finite], expected[finite], rtol=1e-9, atol=1e-9)


# --------------------------------------------------------------------------
# Catalog discovery + registry resolution
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["obv_zscore", "ad_zscore"])
def test_catalog_exposes_zscore_indicator_with_lookback(name):
    info = catalog.info(name)
    assert info is not None, f"{name} missing from catalog"
    assert info.has_lookback is True
    param_names = [p["name"] for p in info.params]
    assert "period" in param_names, f"period not in params: {param_names}"
    period = next(p for p in info.params if p["name"] == "period")
    assert period["default"] == 20
    assert name in set(catalog.list_all(has_lookback=True))


@pytest.mark.parametrize("key", ["OBV_ZSCORE", "AD_ZSCORE"])
def test_registry_resolves_zscore_function(key):
    fn = get_function(key, frequency="day")
    assert fn is not None and callable(fn)
