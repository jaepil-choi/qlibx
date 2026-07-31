"""Regime-aware indicator validation (A1).

Closes a native-surface contradiction that cost a coding agent a ~21-min
root-cause hunt: ``market_regime`` (a regime-classifier *column*, accessed via
the dedicated ``self.get_market_regime()`` accessor, NOT ``get_indicator(...)``)
was handled backwards by two validators —

  * FALSE-NEGATIVE: a list that OMITTED ``market_regime`` passed preflight,
    because ``validate_indicator_names`` scanned only ``get_indicator('x')``
    calls and never saw the dedicated accessor. The bug surfaced only as a
    Stage-2 backtest ``KeyError``.
  * FALSE-POSITIVE: ``catalog.validate`` rejected the agent's CORRECT flat-dict
    fix (``{"market_regime": {}}``) with ``IND-004 "Unknown indicator … did you
    mean ['ma']?"`` — because its regime-classifier acceptance path relies on
    ``is_registered_classifier``, and that runtime registry is EMPTY in the bare
    MCP validator process.

The fix is registry-independent: a static canonical set of regime/session
classifier column names (``KNOWN_REGIME_COLUMNS``) that the validators agree on
even when no host classifier is registered.
"""
import asyncio
import json
import shutil
from pathlib import Path

from echolon.indicators import catalog
from echolon.indicators.registry import is_registered_classifier
from echolon.mcp.server import build_server
from echolon.native.validation.indicator_validator import validate_indicator_names

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "baselines" / "aluminum_baseline"


def _get_tool_fn(name: str):
    server = build_server()
    tm = server._tool_manager
    tools = getattr(tm, "_tools", None) or getattr(tm, "tools", None)
    return tools[name].fn


# --- Change 2: catalog.validate accepts regime columns with an EMPTY registry -

def test_validate_accepts_known_regime_column_without_registration():
    # Precondition: market_regime is host-registered at runtime — absent here.
    assert not is_registered_classifier("market_regime")
    assert catalog.validate({"market_regime": {}}) == []
    assert catalog.validate({"session_phase": {}}) == []


def test_validate_accepts_regime_column_mixed_with_real_indicators():
    assert catalog.validate({"rsi": {"timeperiod": [10, 20]}, "market_regime": {}}) == []


def test_validate_still_rejects_regime_column_typo():
    """The static set must not over-broaden into accepting near-misses."""
    errors = catalog.validate({"market_regimee": {}})
    assert len(errors) == 1
    assert errors[0]["code"] == "IND-004"


# --- Change 1: validate_indicator_names flags an undeclared regime accessor ----

def _write(tmp_path: Path, list_json: str, entry_py: str) -> None:
    (tmp_path / "strategy_indicator_list.json").write_text(list_json, encoding="utf-8")
    (tmp_path / "entry.py").write_text(entry_py, encoding="utf-8")


def test_regime_accessor_requires_declared_column(tmp_path):
    _write(
        tmp_path,
        '{"atr": {"timeperiod": [10, 20]}}',  # market_regime NOT declared
        "def f(self):\n    regime = self.get_market_regime()\n    x = self.get_indicator('atr_14')\n",
    )
    errors = validate_indicator_names(tmp_path)
    assert any(e.code == "IND-002" and "market_regime" in (e.fix or "") for e in errors)


def test_regime_accessor_with_declared_column_passes(tmp_path):
    _write(
        tmp_path,
        '{"atr": {"timeperiod": [10, 20]}, "market_regime": {}}',
        "def f(self):\n    regime = self.get_market_regime()\n    x = self.get_indicator('atr_14')\n",
    )
    errors = validate_indicator_names(tmp_path)
    assert not [e for e in errors if e.code == "IND-002"]


def test_undeclared_regime_column_flagged_once_across_call_sites(tmp_path):
    """One missing declaration == one fix == one IND-002, even when the accessor
    is called many times across files. (The real v20.1 bug had 5 call sites for
    one missing column; 5 findings for one fix is exactly the noise that drove
    the agent's confusion.)"""
    (tmp_path / "strategy_indicator_list.json").write_text('{"atr": {"timeperiod": [10, 20]}}', encoding="utf-8")
    (tmp_path / "entry.py").write_text("def a(self):\n    r = self.get_market_regime()\n", encoding="utf-8")
    (tmp_path / "exit.py").write_text(
        "def b(self):\n    r = self.get_market_regime()\n    s = self.get_market_regime()\n", encoding="utf-8"
    )
    errors = validate_indicator_names(tmp_path)
    ind002_regime = [e for e in errors if e.code == "IND-002" and "market_regime" in (e.fix or "")]
    assert len(ind002_regime) == 1, [e.fix for e in ind002_regime]


def test_session_phase_accessor_requires_declared_column(tmp_path):
    _write(
        tmp_path,
        '{"atr": {"timeperiod": [10, 20]}}',
        "def f(self):\n    phase = self.get_session_phase()\n",
    )
    errors = validate_indicator_names(tmp_path)
    assert any(e.code == "IND-002" and "session_phase" in (e.fix or "") for e in errors)


# --- Change 1b: validate_strategy_full composes validate_indicator_names -------

def test_validate_strategy_full_runs_indicator_names():
    fn = _get_tool_fn("validate_strategy_full")
    result = fn(strategy_dir=str(_FIXTURE_DIR))
    validators = {inv["validator"] for inv in result["invocations"]}
    assert "validate_indicator_names" in validators
    # baseline fixture correctly declares + uses market_regime -> still VALID
    assert result["status"] == "VALID", result["findings"]


def test_validate_strategy_full_catches_undeclared_regime_column(tmp_path):
    dst = tmp_path / "strat"
    shutil.copytree(_FIXTURE_DIR, dst, ignore=shutil.ignore_patterns("__pycache__"))
    il = dst / "strategy_indicator_list.json"
    data = json.loads(il.read_text(encoding="utf-8"))
    data.pop("market_regime", None)
    il.write_text(json.dumps(data), encoding="utf-8")

    fn = _get_tool_fn("validate_strategy_full")
    result = fn(strategy_dir=str(dst))
    assert result["status"] == "INVALID"
    assert any(f["code"] == "IND-002" for f in result["findings"]), result["findings"]


# --- A6: validate_strategy_full composes the indicator-LIST catalog check ----

def test_validate_strategy_full_runs_indicator_list():
    fn = _get_tool_fn("validate_strategy_full")
    result = fn(strategy_dir=str(_FIXTURE_DIR))
    validators = {inv["validator"] for inv in result["invocations"]}
    assert "validate_indicator_list" in validators
    # baseline fixture's flat-dict list is clean -> still VALID
    assert result["status"] == "VALID", result["findings"]


def test_validate_strategy_full_catches_section_keyed_indicator_list(tmp_path):
    dst = tmp_path / "strat"
    shutil.copytree(_FIXTURE_DIR, dst, ignore=shutil.ignore_patterns("__pycache__"))
    il = dst / "strategy_indicator_list.json"
    # rewrite the flat-dict list as a legacy section-keyed payload (G3 bait shape)
    il.write_text(json.dumps({"indicators_with_lookback": {"rsi": [14, 28]}}), encoding="utf-8")

    fn = _get_tool_fn("validate_strategy_full")
    result = fn(strategy_dir=str(dst))
    assert result["status"] == "INVALID"
    assert any(f["code"] == "IND-008" for f in result["findings"]), result["findings"]
