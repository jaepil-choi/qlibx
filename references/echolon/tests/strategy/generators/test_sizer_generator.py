"""Acceptance tests for sizer_generator.

Scaffolder contract:
- Output is a pure-Python module importable via echolon.strategy.loader.
- Defines a class named ``position_sizer`` that subclasses BaseComponent.
- Class exposes a ``calculate_size`` method that takes an EntrySignalOutput
  and returns a SizerOutput with ``calculated_size=1`` (trivial default — agent
  designs the business logic).
- No platform-specific imports (backtrader, miniQMT, etc.).
"""
from pathlib import Path

import pytest

from echolon.strategy.generators.sizer_generator import generate_sizer
from echolon.strategy.loader import StrategyLoader
from echolon.strategy.schemas import EntrySignalOutput, SizerOutput


def test_sizer_generator_writes_module_file(tmp_path: Path):
    out = generate_sizer(strategy_dir=tmp_path)
    assert out == tmp_path / "sizer.py"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


def test_sizer_generator_produces_loadable_module(tmp_path: Path):
    generate_sizer(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("sizer")

    assert hasattr(mod, "position_sizer"), "class name must match loader._REQUIRED_CLASSES"
    cls = mod.position_sizer
    assert hasattr(cls, "calculate_size"), "must expose calculate_size"


def test_sizer_generator_returns_trivial_unit_size(tmp_path: Path):
    """Scaffolder returns fixed 1-unit size by default — agent designs sizing logic later."""
    generate_sizer(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("sizer")

    inst = mod.position_sizer()  # engineless construction — BaseComponent supports trading_engine=None
    entry_signal = EntrySignalOutput(
        signal="HOLD", strength=0.0, type="hold",
        entry_reason="test", intent=None, regime="unknown",
    )
    out = inst.calculate_size(entry_signal)
    assert isinstance(out, SizerOutput)
    assert out.calculated_size == 1


def test_sizer_generator_has_no_platform_imports(tmp_path: Path):
    generate_sizer(strategy_dir=tmp_path)
    text = (tmp_path / "sizer.py").read_text(encoding="utf-8")
    for forbidden in ("import backtrader", "from backtrader", "xtdata", "miniQMT"):
        assert forbidden not in text, f"platform-agnostic rule violated: {forbidden}"


def test_sizer_generator_refuses_to_overwrite_without_force(tmp_path: Path):
    """Silent overwrite is unsafe — raise FileExistsError by default."""
    generate_sizer(strategy_dir=tmp_path)  # first call succeeds

    with pytest.raises(FileExistsError, match="already exists"):
        generate_sizer(strategy_dir=tmp_path)  # second call without force raises


def test_sizer_generator_overwrites_with_force(tmp_path: Path):
    """With force=True, overwrite existing sizer.py."""
    first_path = generate_sizer(strategy_dir=tmp_path)
    (tmp_path / "sizer.py").write_text("# user-modified content", encoding="utf-8")

    generate_sizer(strategy_dir=tmp_path, force=True)
    assert "# user-modified content" not in (tmp_path / "sizer.py").read_text(encoding="utf-8")
