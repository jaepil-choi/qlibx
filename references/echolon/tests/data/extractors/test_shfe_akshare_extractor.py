"""Schema-mapping tests for SHFEAkshareExtractor.

`akshare` is an optional dep — the tests inject a stub module via
sys.modules so we can exercise the extractor's schema mapping without
making the test suite depend on akshare being installed in CI.
"""
from __future__ import annotations
import sys
import types
from typing import Iterable

import pandas as pd
import pytest

from echolon.data.extractors.shfe.akshare_extractor import SHFEAkshareExtractor


_FAKE_DAILY = pd.DataFrame({
    "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
    "open": [19000.0, 19030.0, 19020.0],
    "high": [19050.0, 19080.0, 19070.0],
    "low":  [18990.0, 19000.0, 19000.0],
    "close": [19030.0, 19060.0, 19010.0],
    "volume": [5000.0, 6000.0, 5500.0],
    "hold":  [30000.0, 31000.0, 30500.0],
    "settle": [19020.0, 19040.0, 19025.0],
})


def _install_fake_akshare(monkeypatch, daily_responses: Iterable[pd.DataFrame]):
    """Install a stub akshare module whose futures_zh_daily_sina returns
    the supplied DataFrames in order. Cleanup handled by monkeypatch.
    """
    fake = types.ModuleType("akshare")
    iterator = iter(list(daily_responses))

    def _fake_daily(symbol: str):
        try:
            return next(iterator)
        except StopIteration:
            return pd.DataFrame(columns=_FAKE_DAILY.columns)

    fake.futures_zh_daily_sina = _fake_daily
    monkeypatch.setitem(sys.modules, "akshare", fake)


def test_implements_base_extractor():
    from echolon.data.extractors.base import BaseExtractor
    assert isinstance(SHFEAkshareExtractor("SHFE", "aluminum"), BaseExtractor)


def test_maps_akshare_to_canonical_schema(tmp_path, monkeypatch):
    _install_fake_akshare(monkeypatch, [_FAKE_DAILY])
    extractor = SHFEAkshareExtractor("SHFE", "aluminum")
    monkeypatch.setattr(extractor, "_list_contracts_in_range",
                        lambda *_args, **_kw: ["al2401"])
    df = extractor.extract_raw(
        start_date="2024-01-01", end_date="2024-01-31",
        output_dir=str(tmp_path), save=False,
    )
    for col in ("contract", "date", "open", "high", "low", "close",
                "volume", "open_interest", "settlement",
                "prev_close", "prev_settlement",
                "price_change", "settlement_change", "turnover"):
        assert col in df.columns
    assert (df["contract"] == "al2401").all()
    assert df["settlement"].tolist() == [19020.0, 19040.0, 19025.0]
    assert df["prev_settlement"].tolist() == [19020.0, 19020.0, 19040.0]


def test_falls_back_to_close_when_akshare_settle_missing(tmp_path, monkeypatch):
    no_settle = _FAKE_DAILY.drop(columns=["settle"])
    _install_fake_akshare(monkeypatch, [no_settle])
    extractor = SHFEAkshareExtractor("SHFE", "aluminum")
    monkeypatch.setattr(extractor, "_list_contracts_in_range",
                        lambda *_args, **_kw: ["al2401"])

    df = extractor.extract_raw(
        start_date="2024-01-01", end_date="2024-01-31",
        output_dir=str(tmp_path), save=False,
    )

    assert df["settlement"].tolist() == no_settle["close"].tolist()


def test_skips_empty_contracts(tmp_path, monkeypatch):
    empty = pd.DataFrame(columns=_FAKE_DAILY.columns)
    _install_fake_akshare(monkeypatch, [empty, _FAKE_DAILY])
    extractor = SHFEAkshareExtractor("SHFE", "aluminum")
    monkeypatch.setattr(extractor, "_list_contracts_in_range",
                        lambda *_args, **_kw: ["al2401", "al2407"])
    df = extractor.extract_raw(
        start_date="2024-01-01", end_date="2024-12-31",
        output_dir=str(tmp_path), save=False,
    )
    assert (df["contract"] == "al2407").all()
