"""Tests for `echolon schema` CLI."""

import json

from typer.testing import CliRunner

from echolon.native.cli.main import app


runner = CliRunner()


def test_schema_list():
    result = runner.invoke(app, ["schema", "--list"])
    assert result.exit_code == 0
    assert "BacktestConfig" in result.stdout
    assert "OptunaConfig" in result.stdout


def test_schema_backtest_config():
    result = runner.invoke(app, ["schema", "BacktestConfig"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "properties" in parsed
    assert "start_date" in parsed["properties"]


def test_schema_optuna_config():
    result = runner.invoke(app, ["schema", "OptunaConfig"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "properties" in parsed


def test_schema_unknown_type_fails():
    result = runner.invoke(app, ["schema", "BogusType"])
    assert result.exit_code != 0
