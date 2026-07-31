"""calculator_params.json file format tests.

Tests the v1 schema reader/writer for the paradigm-blind classifier
hyperparameter file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from echolon._internal.strategy_files import (
    load_calculator_params,
    save_calculator_params,
    get_regime_params,
)


# ---------------------------------------------------------------------------
# v1 format
# ---------------------------------------------------------------------------


def test_load_v1_format(tmp_path: Path):
    """calculator_params.json with version=1 schema → returns calculators dict."""
    payload = {
        "version": 1,
        "calculators": {
            "market_regime": {"fast_ma_period": 20, "slow_ma_period": 50},
            "future_carry": {"lookback": 60},
        },
    }
    (tmp_path / "calculator_params.json").write_text(json.dumps(payload))
    assert load_calculator_params(tmp_path) == payload["calculators"]


def test_save_writes_v1_format(tmp_path: Path):
    cp = {"market_regime": {"fast_ma_period": 12}}
    out = save_calculator_params(tmp_path, cp)
    assert out.name == "calculator_params.json"
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["version"] == 1
    assert written["calculators"] == cp


def test_round_trip(tmp_path: Path):
    cp = {"market_regime": {"adx_period": 14}}
    save_calculator_params(tmp_path, cp)
    assert load_calculator_params(tmp_path) == cp


def test_unknown_version_raises(tmp_path: Path):
    """Future schema versions surface a clear error rather than a silent empty dict."""
    (tmp_path / "calculator_params.json").write_text(
        json.dumps({"version": 99, "calculators": {}})
    )
    with pytest.raises(ValueError, match="version"):
        load_calculator_params(tmp_path)


# ---------------------------------------------------------------------------
# Empty / missing
# ---------------------------------------------------------------------------


def test_no_file_returns_empty(tmp_path: Path):
    """Strategy directory with no params file → empty dict (not error)."""
    assert load_calculator_params(tmp_path) == {}


def test_get_regime_params_returns_none_when_absent(tmp_path: Path):
    assert get_regime_params(tmp_path) is None


def test_get_regime_params_extracts_market_regime(tmp_path: Path):
    new = {"version": 1, "calculators": {"market_regime": {"adx_period": 14}}}
    (tmp_path / "calculator_params.json").write_text(json.dumps(new))
    assert get_regime_params(tmp_path) == {"adx_period": 14}


def test_get_regime_params_returns_none_when_only_other_calculators(tmp_path: Path):
    """When calculator_params.json has only e.g. future_carry, market_regime returns None."""
    new = {"version": 1, "calculators": {"future_carry": {"lookback": 60}}}
    (tmp_path / "calculator_params.json").write_text(json.dumps(new))
    assert get_regime_params(tmp_path) is None


# ---------------------------------------------------------------------------
# Path/string flexibility
# ---------------------------------------------------------------------------


def test_accepts_string_path(tmp_path: Path):
    cp = {"market_regime": {"x": 1}}
    save_calculator_params(tmp_path, cp)
    assert load_calculator_params(str(tmp_path)) == cp
