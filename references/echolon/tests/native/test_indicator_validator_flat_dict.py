"""Phase A5 — _get_declared_indicator_names accepts flat-dict payloads.

Legacy 4-section payloads still work (auto-translated).
"""
import json
import textwrap
from pathlib import Path

from echolon.native.validation.indicator_validator import (
    _get_declared_indicator_names,
    validate_indicator_names,
)


def test_declared_names_flat_dict_lookback_expands_range(tmp_path):
    payload = {"rsi": {"timeperiod": [10, 12]}}
    (tmp_path / "strategy_indicator_list.json").write_text(json.dumps(payload))
    names = _get_declared_indicator_names(tmp_path)
    assert names == {"rsi_10", "rsi_11", "rsi_12"}


def test_declared_names_flat_dict_scalar_timeperiod(tmp_path):
    payload = {"atr": {"timeperiod": 14}}
    (tmp_path / "strategy_indicator_list.json").write_text(json.dumps(payload))
    names = _get_declared_indicator_names(tmp_path)
    assert names == {"atr_14"}


def test_declared_names_flat_dict_no_params(tmp_path):
    payload = {"obv": {}, "market_regime": {}}
    (tmp_path / "strategy_indicator_list.json").write_text(json.dumps(payload))
    names = _get_declared_indicator_names(tmp_path)
    assert names == {"obv", "market_regime"}


def test_declared_names_flat_dict_mixed(tmp_path):
    payload = {
        "rsi": {"timeperiod": [10, 11]},
        "atr": {"timeperiod": 14},
        "obv": {},
        "bbands_upper": {},
    }
    (tmp_path / "strategy_indicator_list.json").write_text(json.dumps(payload))
    names = _get_declared_indicator_names(tmp_path)
    assert names == {"rsi_10", "rsi_11", "atr_14", "obv", "bbands_upper"}


def test_declared_names_flat_dict_lookback_without_timeperiod(tmp_path):
    """Lookback indicator with empty params still counts (library default applies)."""
    payload = {"rsi": {}}
    (tmp_path / "strategy_indicator_list.json").write_text(json.dumps(payload))
    names = _get_declared_indicator_names(tmp_path)
    # Without a period, we can't expand; the bare name is declared
    assert "rsi" in names


def test_validate_indicator_names_with_flat_dict(tmp_path):
    (tmp_path / "strategy_indicator_list.json").write_text(
        json.dumps({"rsi": {"timeperiod": 14}})
    )
    (tmp_path / "entry.py").write_text(textwrap.dedent("""\
        def f(self):
            x = self.get_indicator('rsi_14')
    """))
    errors = validate_indicator_names(tmp_path)
    assert errors == []


def test_validate_indicator_names_flat_dict_detects_uppercase(tmp_path):
    (tmp_path / "strategy_indicator_list.json").write_text(
        json.dumps({"atr": {"timeperiod": 14}})
    )
    (tmp_path / "entry.py").write_text(textwrap.dedent("""\
        def f(self):
            x = self.get_indicator('ATR_14')
    """))
    errors = validate_indicator_names(tmp_path)
    assert any(e.code == "IND-001" for e in errors)
