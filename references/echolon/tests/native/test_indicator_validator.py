"""Tests for validate_indicator_names."""

import textwrap
from pathlib import Path

from echolon.native.validation.indicator_validator import validate_indicator_names


def _write_json(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "strategy_indicator_list.json"
    p.write_text(content, encoding="utf-8")
    return p


def _write_entry(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "entry.py"
    p.write_text(textwrap.dedent(content))
    return p


def test_valid_lowercase_indicators_pass(tmp_path):
    _write_json(tmp_path, '{"atr": {"timeperiod": [10, 20]}}')
    _write_entry(tmp_path, """\
        def f(self):
            x = self.get_indicator('atr_14')
    """)
    errors = validate_indicator_names(tmp_path)
    assert errors == []


def test_uppercase_in_code_raises_ind_001(tmp_path):
    _write_json(tmp_path, '{"atr": {"timeperiod": [10, 20]}}')
    _write_entry(tmp_path, """\
        def f(self):
            x = self.get_indicator('ATR_14')
    """)
    errors = validate_indicator_names(tmp_path)
    assert any(e.code == "IND-001" for e in errors)


def test_missing_json_returns_empty(tmp_path):
    errors = validate_indicator_names(tmp_path)
    assert errors == []


def test_multiple_files_checked(tmp_path):
    _write_json(tmp_path, '{"rsi": {"timeperiod": 10}}')
    (tmp_path / "entry.py").write_text("x = self.get_indicator('RSI_10')", encoding="utf-8")
    (tmp_path / "exit.py").write_text("y = self.get_indicator('rsi_10')", encoding="utf-8")
    errors = validate_indicator_names(tmp_path)
    assert len([e for e in errors if e.code == "IND-001"]) >= 1
