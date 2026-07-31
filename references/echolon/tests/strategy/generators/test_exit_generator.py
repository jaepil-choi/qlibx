"""Acceptance tests for exit_generator.

Scaffolder contract:
- Output is a pure-Python module importable via echolon.strategy.loader.
- Defines a class named ``exit_rule`` that subclasses BaseComponent.
- Class exposes a ``should_exit`` method that returns an ExitSignalOutput
  with ``should_exit=False`` (trivial default — agent designs the business logic).
- No platform-specific imports (backtrader, miniQMT, etc.).
"""
from pathlib import Path

import pytest

from echolon.strategy.generators.exit_generator import generate_exit
from echolon.strategy.loader import StrategyLoader
from echolon.strategy.schemas import ExitSignalOutput


def test_exit_generator_writes_module_file(tmp_path: Path):
    out = generate_exit(strategy_dir=tmp_path)
    assert out == tmp_path / "exit.py"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


def test_exit_generator_produces_loadable_module(tmp_path: Path):
    generate_exit(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("exit")

    assert hasattr(mod, "exit_rule"), "class name must match loader._REQUIRED_CLASSES"
    cls = mod.exit_rule
    assert hasattr(cls, "should_exit"), "must expose should_exit"


def test_exit_generator_returns_trivial_no_exit(tmp_path: Path):
    """Scaffolder returns no_exit by default — agent designs pathways later."""
    generate_exit(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("exit")

    inst = mod.exit_rule()  # engineless construction — BaseComponent supports trading_engine=None
    out = inst.should_exit()
    assert isinstance(out, ExitSignalOutput)
    assert out.should_exit is False


def test_exit_generator_has_no_platform_imports(tmp_path: Path):
    generate_exit(strategy_dir=tmp_path)
    text = (tmp_path / "exit.py").read_text(encoding="utf-8")
    for forbidden in ("import backtrader", "from backtrader", "xtdata", "miniQMT"):
        assert forbidden not in text, f"platform-agnostic rule violated: {forbidden}"


def test_exit_generator_refuses_to_overwrite_without_force(tmp_path: Path):
    """Silent overwrite is unsafe — raise FileExistsError by default."""
    generate_exit(strategy_dir=tmp_path)  # first call succeeds

    with pytest.raises(FileExistsError, match="already exists"):
        generate_exit(strategy_dir=tmp_path)  # second call without force raises


def test_exit_generator_overwrites_with_force(tmp_path: Path):
    """With force=True, overwrite existing exit.py."""
    first_path = generate_exit(strategy_dir=tmp_path)
    (tmp_path / "exit.py").write_text("# user-modified content", encoding="utf-8")

    generate_exit(strategy_dir=tmp_path, force=True)
    assert "# user-modified content" not in (tmp_path / "exit.py").read_text(encoding="utf-8")
