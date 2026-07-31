"""
Tests for the carry indicator shared utilities (Gate 1C WS2 B2.2).
"""
from __future__ import annotations

import pandas as pd
import pytest

from echolon.errors import IndicatorError
from echolon.indicators.calculators.interday.carry.utils import (
    days_to_expiry_pair,
    extract_settlement,
    front_back_settlements,
)


def _bar_row(close: float = 22100.0, settlement: float = 22115.5) -> pd.Series:
    """Synthetic OHLCV+settlement row matching the FUTURES_COLUMNS schema."""
    return pd.Series({
        "date": pd.Timestamp("2024-06-05"),
        "open": close - 5,
        "high": close + 20,
        "low": close - 25,
        "close": close,
        "volume": 1000.0,
        "settlement": settlement,
        "open_interest": 5000.0,
    })


# ---------------------------------------------------------------------------
# extract_settlement
# ---------------------------------------------------------------------------


def test_extract_settlement_returns_settlement_not_close():
    """The whole point of the Q50 spike — settlement is a separate column.
    extract_settlement must pull it, NOT close."""
    row = _bar_row(close=22100.0, settlement=22115.5)
    assert extract_settlement(row) == 22115.5


def test_extract_settlement_returns_python_float():
    row = _bar_row()
    out = extract_settlement(row)
    assert isinstance(out, float)


def test_extract_settlement_missing_column_raises_ind_005():
    row = pd.Series({"close": 22100.0, "volume": 1000.0})
    with pytest.raises(IndicatorError) as exc:
        extract_settlement(row)
    assert exc.value.code == "IND-005"
    assert "settlement" in str(exc.value)


# ---------------------------------------------------------------------------
# front_back_settlements
# ---------------------------------------------------------------------------


def test_front_back_settlements_returns_iloc_0_and_1():
    snap = pd.DataFrame({
        "contract": ["zn2407", "zn2408", "zn2409"],
        "settlement": [22100.0, 22150.0, 22180.0],
        "days_to_expiry": [25, 56, 84],
    })
    front, back = front_back_settlements(snap)
    assert front == 22100.0
    assert back == 22150.0


def test_front_back_settlements_too_few_contracts_raises():
    snap = pd.DataFrame({"settlement": [22100.0]})
    with pytest.raises(ValueError, match="at least 2"):
        front_back_settlements(snap)


def test_front_back_settlements_missing_settlement_raises_ind_005():
    snap = pd.DataFrame({"close": [22100.0, 22150.0]})
    with pytest.raises(IndicatorError) as exc:
        front_back_settlements(snap)
    assert exc.value.code == "IND-005"


# ---------------------------------------------------------------------------
# days_to_expiry_pair
# ---------------------------------------------------------------------------


def test_days_to_expiry_pair_returns_iloc_0_and_1_as_ints():
    snap = pd.DataFrame({
        "settlement": [22100.0, 22150.0, 22180.0],
        "days_to_expiry": [25, 56, 84],
    })
    front_dte, back_dte = days_to_expiry_pair(snap)
    assert front_dte == 25
    assert back_dte == 56
    assert isinstance(front_dte, int)
    assert isinstance(back_dte, int)
