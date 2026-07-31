"""Tests for the unified StrategyLoader."""

import textwrap
from pathlib import Path

import pytest

from echolon.strategy.loader import StrategyLoader


@pytest.fixture
def strategy_dir(tmp_path):
    """Create a temporary strategy directory with sample modules."""
    (tmp_path / "strategy_params.py").write_text(textwrap.dedent("""\
        DEFAULT_PARAMS = {"entry_params": {"lookback": 20}}
        optuna_search_space = {"entry_lookback": [10, 50]}
        framework = "interday"

        def apply_shared_params(trial, params):
            return params
    """))

    (tmp_path / "entry.py").write_text(textwrap.dedent("""\
        class entry_rule:
            name = "test_entry"
    """))

    (tmp_path / "strategy.py").write_text(textwrap.dedent("""\
        def strategy_main(**kwargs):
            return "strategy_instance"
    """))

    return tmp_path


def test_load_module(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    mod = loader.load_module("strategy_params")
    assert hasattr(mod, "DEFAULT_PARAMS")
    assert mod.DEFAULT_PARAMS == {"entry_params": {"lookback": 20}}


def test_load_attr(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    space = loader.load_attr("strategy_params", "optuna_search_space")
    assert space == {"entry_lookback": [10, 50]}


def test_load_function(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    fn = loader.load_function("strategy", "strategy_main")
    assert callable(fn)
    assert fn() == "strategy_instance"


def test_load_class(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    cls = loader.load_class("entry", "entry_rule")
    assert cls.name == "test_entry"


def test_load_missing_module(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    with pytest.raises(FileNotFoundError):
        loader.load_module("nonexistent")


def test_load_missing_attr(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    with pytest.raises(AttributeError):
        loader.load_attr("strategy_params", "nonexistent_attr")


def test_cache_and_clear(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    mod1 = loader.load_module("strategy_params")
    mod2 = loader.load_module("strategy_params")
    assert mod1 is mod2  # cached

    loader.clear_cache()
    mod3 = loader.load_module("strategy_params")
    assert mod3 is not mod1  # reloaded


def test_has_module(strategy_dir):
    loader = StrategyLoader(strategy_dir)
    assert loader.has_module("strategy_params")
    assert not loader.has_module("nonexistent")
