"""Tests for `echolon migrate` CLI."""

from pathlib import Path

from typer.testing import CliRunner

from echolon.native.cli.main import app


runner = CliRunner()


def test_migrate_rewrites_simple_import(tmp_path):
    (tmp_path / "a.py").write_text(
        "from echolon.quant_engine.backtest import BacktestRunner\n"
    )
    result = runner.invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0
    assert "from echolon.backtest import BacktestRunner" in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_migrate_rewrites_nested_import(tmp_path):
    (tmp_path / "a.py").write_text(
        "from echolon.quant_engine.deploy.engine.portfolio_trading_runner import PortfolioTradingRunner\n"
    )
    result = runner.invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0
    assert "from echolon.live.orchestrator.portfolio import PortfolioTradingRunner" in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_migrate_dry_run_does_not_write(tmp_path):
    original = "from echolon.quant_engine.backtest import BacktestRunner\n"
    (tmp_path / "a.py").write_text(original, encoding="utf-8")
    result = runner.invoke(app, ["migrate", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == original


def test_migrate_handles_import_as(tmp_path):
    (tmp_path / "a.py").write_text(
        "import echolon.quant_engine.backtest as be\n"
    )
    result = runner.invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0
    assert "import echolon.backtest as be" in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_migrate_reports_file_count(tmp_path):
    (tmp_path / "a.py").write_text("from echolon.quant_engine.backtest import X\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from echolon.data_pipeline.extractors import Y\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("# no imports to change\n", encoding="utf-8")
    result = runner.invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0
    assert "2" in result.stdout


def test_migrate_skips_non_py_files(tmp_path):
    (tmp_path / "file.txt").write_text(
        "from echolon.quant_engine.backtest import X\n"
    )
    result = runner.invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0
    assert "from echolon.quant_engine.backtest" in (tmp_path / "file.txt").read_text(encoding="utf-8")


def test_migrate_rewrites_common_mappings(tmp_path):
    """Smoke test covering the most common mappings."""
    test_cases = [
        ("from echolon.data_pipeline import X", "from echolon.data import X"),
        ("from echolon.native.validation.errors import X", "from echolon.errors import X"),
        ("from echolon.quant_engine.types import X", "from echolon.strategy.schemas import X"),
        ("from echolon.quant_engine.market_adapters.shfe.shfe_adapter import X", "from echolon.markets.shfe.adapter import X"),
        ("from echolon.indicators.run_indicators import X", "from echolon.indicators.run import X"),
    ]
    src_lines = "\n".join(old for old, _ in test_cases) + "\n"
    expected_lines = "\n".join(new for _, new in test_cases) + "\n"
    (tmp_path / "test.py").write_text(src_lines, encoding="utf-8")

    result = runner.invoke(app, ["migrate", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "test.py").read_text(encoding="utf-8") == expected_lines
