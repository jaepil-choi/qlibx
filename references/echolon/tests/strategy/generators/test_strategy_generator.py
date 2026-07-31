"""Acceptance tests for strategy_generator.

Scaffolder contract:
- Output is a pure-Python module loadable via StrategyLoader.load_function.
- Defines class ``strategy_main`` subclassing BaseStrategy.
- Exposes ``_execute_bar`` method (the canonical coordination entry point).
- Contains no platform-specific imports.
"""
from pathlib import Path

import pytest

from echolon.strategy.base import BaseStrategy
from echolon.strategy.generators.strategy_generator import generate_strategy
from echolon.strategy.loader import StrategyLoader


def test_strategy_generator_writes_module_file(tmp_path: Path):
    out = generate_strategy(strategy_dir=tmp_path)
    assert out == tmp_path / "strategy.py"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


def test_strategy_generator_produces_loadable_coordinator(tmp_path: Path):
    generate_strategy(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("strategy")

    assert hasattr(mod, "strategy_main"), "class name must match loader's strategy_main convention"
    cls = mod.strategy_main
    assert issubclass(cls, BaseStrategy), "must subclass BaseStrategy"
    assert hasattr(cls, "_execute_bar"), "must expose _execute_bar"


def test_strategy_generator_has_canonical_execute_bar(tmp_path: Path):
    """Scaffold body calls the 4 components in canonical order."""
    generate_strategy(strategy_dir=tmp_path)
    text = (tmp_path / "strategy.py").read_text(encoding="utf-8")
    # Presence of the 4 canonical coordination calls (order matters for the
    # standard dispatch flow).
    risk_pos = text.find("self.risk_manager.can_trade()")
    exit_pos = text.find("self.exit_rule.should_exit()")
    entry_pos = text.find("self.entry_rule.generate_signal()")
    sizer_pos = text.find("self.position_sizer.calculate_size(")
    assert 0 <= risk_pos < exit_pos < entry_pos < sizer_pos, (
        f"canonical dispatch order violated: risk={risk_pos}, exit={exit_pos}, "
        f"entry={entry_pos}, sizer={sizer_pos}"
    )


def test_strategy_generator_has_no_platform_imports(tmp_path: Path):
    generate_strategy(strategy_dir=tmp_path)
    text = (tmp_path / "strategy.py").read_text(encoding="utf-8")
    for forbidden in ("import backtrader", "from backtrader", "xtdata", "miniQMT"):
        assert forbidden not in text, f"platform-agnostic rule violated: {forbidden}"


def test_strategy_generator_refuses_to_overwrite_without_force(tmp_path: Path):
    generate_strategy(strategy_dir=tmp_path)

    with pytest.raises(FileExistsError, match="already exists"):
        generate_strategy(strategy_dir=tmp_path)


def test_strategy_generator_overwrites_with_force(tmp_path: Path):
    generate_strategy(strategy_dir=tmp_path)
    (tmp_path / "strategy.py").write_text("# user-modified content", encoding="utf-8")

    generate_strategy(strategy_dir=tmp_path, force=True)
    assert "# user-modified content" not in (tmp_path / "strategy.py").read_text(encoding="utf-8")
