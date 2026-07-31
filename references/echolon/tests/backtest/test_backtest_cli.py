"""Tests for `echolon backtest portfolio` CLI."""
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from echolon.native.cli.main import app

runner = CliRunner()


def test_backtest_help_lists_portfolio():
    result = runner.invoke(app, ["backtest", "--help"])
    assert result.exit_code == 0
    assert "portfolio" in result.stdout


def test_backtest_portfolio_invokes_runner(tmp_path):
    cfg = tmp_path / "portfolio_deploy_config.json"
    cfg.write_text('{"slots": [], "schedule": {}, "account": {}, "deploy": {}}', encoding="utf-8")
    output_dir = tmp_path / "portfolio_backtest"

    with patch("echolon.backtest.cli.PortfolioBacktestRunner") as MockRunner, \
         patch("echolon.backtest.cli.PortfolioDeployConfig.load") as MockLoad:
        mock_config = MagicMock()
        mock_config.get_enabled_slots.return_value = []
        MockLoad.return_value = mock_config
        runner_instance = MagicMock()
        runner_instance.run.return_value = {"portfolio_metrics": {"sharpe_ratio": 1.5}}
        runner_instance.run_per_window.return_value = {"windows": []}
        MockRunner.return_value = runner_instance

        result = runner.invoke(app, [
            "backtest", "portfolio",
            "--config", str(cfg),
            "--output-dir", str(output_dir),
            "--start", "2020-01-01",
            "--end", "2023-12-31",
        ])

        assert result.exit_code == 0, result.stdout
        runner_instance.run.assert_called_once()
        # run() gets dates passed
        call_kwargs = runner_instance.run.call_args.kwargs
        assert call_kwargs.get("start_date") == "2020-01-01"
        assert call_kwargs.get("end_date") == "2023-12-31"
        # run_per_window also called by default
        runner_instance.run_per_window.assert_called_once()


def test_backtest_portfolio_skip_per_window_flag(tmp_path):
    cfg = tmp_path / "portfolio_deploy_config.json"
    cfg.write_text('{"slots": [], "schedule": {}, "account": {}, "deploy": {}}', encoding="utf-8")

    with patch("echolon.backtest.cli.PortfolioBacktestRunner") as MockRunner, \
         patch("echolon.backtest.cli.PortfolioDeployConfig.load") as MockLoad:
        mock_config = MagicMock()
        mock_config.get_enabled_slots.return_value = []
        MockLoad.return_value = mock_config
        runner_instance = MagicMock()
        runner_instance.run.return_value = {"portfolio_metrics": {}}
        MockRunner.return_value = runner_instance

        result = runner.invoke(app, [
            "backtest", "portfolio",
            "--config", str(cfg),
            "--output-dir", str(tmp_path / "out"),
            "--start", "2020-01-01",
            "--end", "2020-12-31",
            "--skip-per-window",
        ])

        assert result.exit_code == 0, result.stdout
        runner_instance.run.assert_called_once()
        runner_instance.run_per_window.assert_not_called()
