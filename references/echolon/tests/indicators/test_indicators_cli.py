"""Tests for echolon indicators CLI."""
import json
from typer.testing import CliRunner

from echolon.native.cli.main import app

runner = CliRunner()


def test_indicators_list_json_format():
    result = runner.invoke(app, ["indicators", "list", "--format", "json"])
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    assert len(data) > 0  # some indicators should be listed
    # Each entry should describe the indicator's callable params
    sample_name = next(iter(data.keys()))
    assert isinstance(data[sample_name], dict)


def test_indicators_list_text_format():
    result = runner.invoke(app, ["indicators", "list", "--format", "text"])
    assert result.exit_code == 0
    assert "rsi" in result.stdout.lower() or "macd" in result.stdout.lower()
