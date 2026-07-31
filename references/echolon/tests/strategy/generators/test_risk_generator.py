"""Acceptance tests for risk_generator.

Scaffolder contract:
- Output is a pure-Python module importable via echolon.strategy.loader.
- Defines a class named ``risk_manager`` that subclasses BaseComponent.
- Class exposes a ``can_trade`` method that returns a RiskOutput
  with ``trading_allowed=True`` (trivial default — agent designs the business logic).
- No platform-specific imports (backtrader, miniQMT, etc.).
"""
from pathlib import Path

import pytest

from echolon.strategy.generators.risk_generator import generate_risk
from echolon.strategy.loader import StrategyLoader
from echolon.strategy.schemas import RiskOutput


def test_risk_generator_writes_module_file(tmp_path: Path):
    out = generate_risk(strategy_dir=tmp_path)
    assert out == tmp_path / "risk.py"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


def test_risk_generator_produces_loadable_module(tmp_path: Path):
    generate_risk(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("risk")

    assert hasattr(mod, "risk_manager"), "class name must match loader._REQUIRED_CLASSES"
    cls = mod.risk_manager
    assert hasattr(cls, "can_trade"), "must expose can_trade"


def test_risk_generator_returns_trivial_trading_allowed(tmp_path: Path):
    """Scaffolder returns trading_allowed by default — agent designs checks later."""
    generate_risk(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("risk")

    inst = mod.risk_manager()  # engineless construction — BaseComponent supports trading_engine=None
    out = inst.can_trade()
    assert isinstance(out, RiskOutput)
    assert out.trading_allowed is True


def test_risk_generator_has_no_platform_imports(tmp_path: Path):
    generate_risk(strategy_dir=tmp_path)
    text = (tmp_path / "risk.py").read_text(encoding="utf-8")
    for forbidden in ("import backtrader", "from backtrader", "xtdata", "miniQMT"):
        assert forbidden not in text, f"platform-agnostic rule violated: {forbidden}"


def test_risk_generator_refuses_to_overwrite_without_force(tmp_path: Path):
    """Silent overwrite is unsafe — raise FileExistsError by default."""
    generate_risk(strategy_dir=tmp_path)  # first call succeeds

    with pytest.raises(FileExistsError, match="already exists"):
        generate_risk(strategy_dir=tmp_path)  # second call without force raises


def test_risk_generator_overwrites_with_force(tmp_path: Path):
    """With force=True, overwrite existing risk.py."""
    first_path = generate_risk(strategy_dir=tmp_path)
    (tmp_path / "risk.py").write_text("# user-modified content", encoding="utf-8")

    generate_risk(strategy_dir=tmp_path, force=True)
    assert "# user-modified content" not in (tmp_path / "risk.py").read_text(encoding="utf-8")
