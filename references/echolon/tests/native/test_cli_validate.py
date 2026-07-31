"""Tests for `echolon validate` CLI."""

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from echolon.native.cli.main import app


runner = CliRunner()


MINIMAL = {
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


def _make_valid(tmp_path: Path) -> Path:
    for filename, content in MINIMAL.items():
        (tmp_path / filename).write_text(textwrap.dedent(content))
    return tmp_path


def test_validate_valid_strategy_exits_zero(tmp_path):
    _make_valid(tmp_path)
    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 0


def test_validate_missing_file_exits_one(tmp_path):
    _make_valid(tmp_path)
    (tmp_path / "entry.py").unlink()
    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "STR-001" in result.stdout


def test_validate_json_output(tmp_path):
    _make_valid(tmp_path)
    (tmp_path / "entry.py").unlink()
    result = runner.invoke(app, ["validate", str(tmp_path), "--json"])
    assert result.exit_code == 1
    parsed = json.loads(result.stdout)
    assert parsed["status"] == "failed"
    assert len(parsed["errors"]) >= 1
    assert parsed["errors"][0]["code"] == "STR-001"
    assert "docs_url" in parsed["errors"][0]


def test_validate_json_valid_strategy(tmp_path):
    _make_valid(tmp_path)
    result = runner.invoke(app, ["validate", str(tmp_path), "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["status"] == "ok"
    assert parsed["errors"] == []
