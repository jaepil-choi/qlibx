"""Tests for validate_strategy_dir."""

import textwrap
from pathlib import Path

import pytest

from echolon.native.validation.strategy_validator import (
    validate_strategy_dir,
    REQUIRED_FILES,
)

MINIMAL_STRATEGY_FILES = {
    "strategy.py": """\
        from echolon.strategy.base import BaseStrategy
        class strategy_main(BaseStrategy):
            def __init__(self, trading_engine, **params):
                super().__init__(trading_engine, **params)
            def _execute_bar(self):
                pass
    """,
    "entry.py": """\
        from echolon.strategy.component import BaseComponent
        class entry_rule(BaseComponent):
            def __init__(self, trading_engine, **params):
                super().__init__(trading_engine, **params)
            def generate_signal(self):
                pass
    """,
    "exit.py": """\
        from echolon.strategy.component import BaseComponent
        class exit_rule(BaseComponent):
            def __init__(self, trading_engine, **params):
                super().__init__(trading_engine, **params)
            def should_exit(self):
                pass
    """,
    "risk.py": """\
        from echolon.strategy.component import BaseComponent
        class risk_manager(BaseComponent):
            def __init__(self, trading_engine, **params):
                super().__init__(trading_engine, **params)
            def can_trade(self):
                pass
    """,
    "sizer.py": """\
        from echolon.strategy.component import BaseComponent
        class position_sizer(BaseComponent):
            def __init__(self, trading_engine, **params):
                super().__init__(trading_engine, **params)
            def calculate_size(self, signal_data):
                pass
    """,
    "strategy_params.py": """\
        DEFAULT_PARAMS = {
            "entry_params": {"printlog": False},
            "exit_params": {"printlog": False},
            "risk_params": {"printlog": False},
            "sizer_params": {"printlog": False},
        }
        def optuna_search_space(trial):
            return DEFAULT_PARAMS
        def apply_shared_params(params):
            return params
        framework = None
    """,
    "strategy_indicator_list.json": """\
        {"market_regime": {}}
    """,
}


@pytest.fixture
def valid_strategy(tmp_path):
    for filename, content in MINIMAL_STRATEGY_FILES.items():
        (tmp_path / filename).write_text(textwrap.dedent(content))
    return tmp_path


def test_required_files_constant():
    assert set(REQUIRED_FILES) == {
        "strategy.py", "entry.py", "exit.py", "risk.py", "sizer.py",
        "strategy_params.py", "strategy_indicator_list.json",
    }


def test_valid_strategy_passes(valid_strategy):
    errors = validate_strategy_dir(valid_strategy)
    assert errors == []


def test_missing_file_raises_str_001(valid_strategy):
    (valid_strategy / "entry.py").unlink()
    errors = validate_strategy_dir(valid_strategy)
    assert len(errors) >= 1
    assert any(e.code == "STR-001" for e in errors)


def test_nonexistent_directory_raises(tmp_path):
    errors = validate_strategy_dir(tmp_path / "does_not_exist")
    assert any(e.code == "STR-001" for e in errors)


def test_missing_class_in_file_raises_str_002(valid_strategy):
    (valid_strategy / "entry.py").write_text(textwrap.dedent("""\
        from echolon.strategy.component import BaseComponent
        class wrong_name(BaseComponent):
            pass
    """))
    errors = validate_strategy_dir(valid_strategy)
    assert any(e.code == "STR-002" for e in errors)


def test_missing_printlog_raises_prm_001(valid_strategy):
    (valid_strategy / "strategy_params.py").write_text(textwrap.dedent("""\
        DEFAULT_PARAMS = {
            "entry_params": {},
            "exit_params": {"printlog": False},
            "risk_params": {"printlog": False},
            "sizer_params": {"printlog": False},
        }
        def optuna_search_space(trial):
            return DEFAULT_PARAMS
        def apply_shared_params(params):
            return params
        framework = None
    """))
    errors = validate_strategy_dir(valid_strategy)
    assert any(e.code == "PRM-001" for e in errors)


def test_wrong_default_params_shape_raises_prm_002(valid_strategy):
    (valid_strategy / "strategy_params.py").write_text(textwrap.dedent("""\
        DEFAULT_PARAMS = {"only_one_key": {"printlog": False}}
        def optuna_search_space(trial):
            return DEFAULT_PARAMS
        def apply_shared_params(params):
            return params
        framework = None
    """))
    errors = validate_strategy_dir(valid_strategy)
    assert any(e.code == "PRM-002" for e in errors)


def test_returns_all_errors_not_just_first(valid_strategy):
    (valid_strategy / "entry.py").unlink()
    (valid_strategy / "exit.py").unlink()
    errors = validate_strategy_dir(valid_strategy)
    assert len(errors) >= 1
