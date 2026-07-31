"""Q48 (NEGATIVE) — multi-frequency `load_ohlcv` support.

Per qorka docs/4_plans/wave_1/2026-05-13-gate-1a-foundation.md T23.
Storage layout:
- Daily (frequency="1d"): legacy ``{market_data_dir}/{MARKET}/{asset}/sort_by_date.csv``
- Intraday (1m/5m/15m/1h): ``{market_data_dir}/{MARKET}/{asset}/{frequency}/sort_by_date.csv``

Backward compatibility: the default `frequency="1d"` reads from the legacy
single-file path, so all pre-2026-05-13 callers continue working.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from echolon.data.loaders.ohlcv_loader import (
    SUPPORTED_FREQUENCIES,
    load_ohlcv,
)


# ---------------------------------------------------------------------------
# Schema + signature
# ---------------------------------------------------------------------------

def test_supported_frequencies_match_spec():
    """Per Q48 spec — exactly these 5 frequencies are supported."""
    assert SUPPORTED_FREQUENCIES == {"1d", "1m", "5m", "15m", "1h"}


def test_load_ohlcv_accepts_frequency_param():
    """Signature change: `frequency` is a keyword argument with default '1d'."""
    import inspect
    sig = inspect.signature(load_ohlcv)
    assert "frequency" in sig.parameters
    assert sig.parameters["frequency"].default == "1d"
    # `frequency` is a keyword-only param (after `*`)
    assert sig.parameters["frequency"].kind == inspect.Parameter.KEYWORD_ONLY


def test_load_ohlcv_rejects_unsupported_frequency(tmp_path):
    """Invalid frequency raises DAT-005 (DataError) per echolon error
    catalog — NOT a generic ValueError + NOT a DAT-001 path-not-found
    (which would confuse the caller about whether the file exists)."""
    from echolon.errors import DataError

    with pytest.raises(DataError, match="DAT-005"):
        load_ohlcv(
            market="SHFE",
            asset="aluminum",
            market_data_dir=tmp_path,
            frequency="1y",  # not supported
        )


# ---------------------------------------------------------------------------
# Backward compatibility — frequency="1d" reads legacy layout
# ---------------------------------------------------------------------------

def _write_daily_fixture(tmp_path, market="SHFE", asset="aluminum"):
    asset_dir = tmp_path / market / asset
    asset_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=5, freq="D"),
        "open": [24600, 24650, 24700, 24750, 24800],
        "high": [24700, 24750, 24800, 24850, 24900],
        "low": [24550, 24600, 24650, 24700, 24750],
        "close": [24680, 24720, 24770, 24820, 24870],
        "volume": [1000, 1100, 1200, 1300, 1400],
    })
    df.to_csv(asset_dir / "sort_by_date.csv", index=False)
    return tmp_path


def test_load_ohlcv_default_frequency_reads_legacy_layout(tmp_path):
    """Default frequency='1d' reads from legacy single-file path —
    backward-compat for all pre-2026-05-13 callers."""
    market_data_dir = _write_daily_fixture(tmp_path)

    df = load_ohlcv(
        market="SHFE", asset="aluminum", market_data_dir=market_data_dir
    )
    assert len(df) == 5
    assert "date" in df.columns
    assert df["close"].iloc[0] == 24680.0


def test_load_ohlcv_explicit_daily_same_as_default(tmp_path):
    """`frequency='1d'` explicit form behaves identically to default."""
    market_data_dir = _write_daily_fixture(tmp_path)

    df_default = load_ohlcv(
        market="SHFE", asset="aluminum", market_data_dir=market_data_dir
    )
    df_explicit = load_ohlcv(
        market="SHFE", asset="aluminum", market_data_dir=market_data_dir, frequency="1d"
    )
    pd.testing.assert_frame_equal(df_default, df_explicit)


# ---------------------------------------------------------------------------
# Intraday — new frequency-disambiguated layout
# ---------------------------------------------------------------------------

def _write_intraday_fixture(tmp_path, frequency, market="SHFE", asset="aluminum"):
    asset_dir = tmp_path / market / asset / frequency
    asset_dir.mkdir(parents=True)
    df = pd.DataFrame({
        "datetime": pd.date_range("2025-01-01 09:00", periods=20, freq="15min"),
        "open": range(24600, 24620),
        "high": range(24650, 24670),
        "low": range(24550, 24570),
        "close": range(24620, 24640),
        "volume": [100] * 20,
    })
    df.to_csv(asset_dir / "sort_by_date.csv", index=False)
    return tmp_path


@pytest.mark.parametrize("frequency", ["1m", "5m", "15m", "1h"])
def test_load_ohlcv_intraday_reads_frequency_subdir(tmp_path, frequency):
    """Intraday frequencies resolve to {frequency}/sort_by_date.csv subpath."""
    market_data_dir = _write_intraday_fixture(tmp_path, frequency=frequency)

    df = load_ohlcv(
        market="SHFE",
        asset="aluminum",
        market_data_dir=market_data_dir,
        frequency=frequency,
    )
    assert len(df) == 20
    assert "datetime" in df.columns


def test_load_ohlcv_intraday_does_not_read_daily_file(tmp_path):
    """A daily fixture should NOT be read by an intraday call — the
    frequency-disambiguated path resolution prevents accidental fallback."""
    market_data_dir = _write_daily_fixture(tmp_path)

    # Daily fixture exists; intraday subdir does NOT
    with pytest.raises(Exception):  # echolon DAT-001 or similar
        load_ohlcv(
            market="SHFE",
            asset="aluminum",
            market_data_dir=market_data_dir,
            frequency="15m",
        )


# ---------------------------------------------------------------------------
# Date-range filter works for both daily + intraday
# ---------------------------------------------------------------------------

def test_load_ohlcv_date_filter_works_for_intraday(tmp_path):
    """For intraday data, filter is applied to 'datetime' column.

    Note: `start_date`/`end_date` strings parse to midnight (00:00:00).
    Intraday callers wanting to include a full day should pass the next
    day's date as `end_date`. UX improvement (end-of-day semantics for
    intraday) is a follow-up — current behavior matches daily-data convention.
    """
    market_data_dir = _write_intraday_fixture(tmp_path, frequency="15m")

    df = load_ohlcv(
        market="SHFE",
        asset="aluminum",
        market_data_dir=market_data_dir,
        frequency="15m",
        start_date="2025-01-01",
        end_date="2025-01-02",  # next-day boundary to include all 2025-01-01 bars
    )
    # All 20 bars are on 2025-01-01 (09:00 onward); end_date=2025-01-02 includes them
    assert len(df) == 20
    assert df["datetime"].dt.date.nunique() == 1


def test_load_ohlcv_intraday_start_date_filter(tmp_path):
    """Verify start_date filter is applied to 'datetime' column."""
    market_data_dir = _write_intraday_fixture(tmp_path, frequency="15m")

    df = load_ohlcv(
        market="SHFE",
        asset="aluminum",
        market_data_dir=market_data_dir,
        frequency="15m",
        start_date="2025-01-01 11:00",  # mid-fixture start
    )
    # Fixture has 20 bars at 09:00, 09:15, 09:30, ..., 13:45 (15-min × 20 = 5 hours)
    # 11:00 cutoff includes bars at 11:00 and later (from index 8 onward = 12 bars)
    assert len(df) == 12


def test_load_ohlcv_date_filter_works_for_daily(tmp_path):
    """For daily data, filter is applied to 'date' column (backward-compat)."""
    market_data_dir = _write_daily_fixture(tmp_path)

    df = load_ohlcv(
        market="SHFE",
        asset="aluminum",
        market_data_dir=market_data_dir,
        start_date="2025-01-02",
        end_date="2025-01-04",
    )
    assert len(df) == 3
