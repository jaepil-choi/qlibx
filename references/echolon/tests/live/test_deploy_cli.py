"""Tests for `echolon deploy` CLI sub-app."""
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from echolon.native.cli.main import app

runner = CliRunner()


def test_deploy_help_shows_subcommands():
    """`echolon deploy --help` should list portfolio + portfolio-cycle subcommands."""
    result = runner.invoke(app, ["deploy", "--help"])
    assert result.exit_code == 0
    assert "portfolio" in result.stdout
    assert "portfolio-cycle" in result.stdout


def test_deploy_portfolio_invokes_portfolio_runner(tmp_path):
    """`echolon deploy portfolio --config X` runs PortfolioTradingRunner."""
    cfg = tmp_path / "portfolio_deploy_config.json"
    cfg.write_text('{"slots": [], "schedule": {}, "account": {}, "deploy": {}}', encoding="utf-8")

    with patch("echolon.live.cli.PortfolioTradingRunner") as MockRunner, \
         patch("echolon.live.cli.PortfolioDeployConfig.load") as MockLoad:
        mock_config = MagicMock()
        mock_config.get_enabled_slots.return_value = []
        MockLoad.return_value = mock_config
        runner_instance = MagicMock()
        MockRunner.return_value = runner_instance

        result = runner.invoke(app, ["deploy", "portfolio", "--config", str(cfg)])

        assert result.exit_code == 0, result.stdout
        MockLoad.assert_called_once_with(str(cfg))
        runner_instance.run.assert_called_once()
        runner_instance.stop.assert_called_once()


def test_deploy_portfolio_cycle_runs_single_cycle(tmp_path):
    """`echolon deploy portfolio-cycle` calls run_single_cycle once."""
    cfg = tmp_path / "portfolio_deploy_config.json"
    cfg.write_text('{"slots": [], "schedule": {}, "account": {}, "deploy": {}}', encoding="utf-8")

    with patch("echolon.live.cli.PortfolioTradingRunner") as MockRunner, \
         patch("echolon.live.cli.PortfolioDeployConfig.load") as MockLoad:
        mock_config = MagicMock()
        mock_config.get_enabled_slots.return_value = []
        MockLoad.return_value = mock_config
        runner_instance = MagicMock()
        runner_instance.run_single_cycle.return_value = {"status": "ok"}
        MockRunner.return_value = runner_instance

        result = runner.invoke(app, ["deploy", "portfolio-cycle", "--config", str(cfg)])

        assert result.exit_code == 0, result.stdout
        runner_instance.run_single_cycle.assert_called_once()
        runner_instance.stop.assert_called_once()


def test_deploy_portfolio_validate_only_skips_run(tmp_path):
    """`--validate-only` loads config but does not start the runner."""
    cfg = tmp_path / "portfolio_deploy_config.json"
    cfg.write_text('{"slots": [], "schedule": {}, "account": {}, "deploy": {}}', encoding="utf-8")

    with patch("echolon.live.cli.PortfolioTradingRunner") as MockRunner, \
         patch("echolon.live.cli.PortfolioDeployConfig.load") as MockLoad:
        mock_config = MagicMock()
        mock_config.get_enabled_slots.return_value = []
        MockLoad.return_value = mock_config

        result = runner.invoke(app, ["deploy", "portfolio", "--config", str(cfg), "--validate-only"])

        assert result.exit_code == 0, result.stdout
        MockRunner.assert_not_called()


def test_portfolio_config_resolves_relative_strategy_paths(tmp_path):
    """PortfolioDeployConfig.load() should resolve strategy_code_dir / trial_params_path
    relative to the config file's directory (not CWD)."""
    from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig

    config_dir = tmp_path / "goingmerry"
    config_dir.mkdir()
    cfg = config_dir / "portfolio_deploy_config.json"
    cfg.write_text('''{
        "slots": [{
            "slot_id": "al_s1", "strategy_id": "al_test",
            "cluster": "al", "version": "1.0",
            "instrument": "aluminum", "instrument_code": "al",
            "market": "SHFE", "frequency": "interday", "bar_size": "1d",
            "initial_capital": 100000.0,
            "strategy_code_dir": "./strategies/al_s1/current",
            "trial_params_path": "./strategies/al_s1/current/selected_robust_trial.json",
            "enabled": true,
            "dashboard": {}
        }],
        "schedule": {}, "account": {},
        "deploy": {"max_total_capital": 1000.0}
    }''')

    config = PortfolioDeployConfig.load(str(cfg))
    slot = config.slots[0]
    # After load(), the paths should be absolute and anchored to config_dir
    assert str(config_dir) in slot.strategy_code_dir, f"expected absolute path, got {slot.strategy_code_dir}"
    # Normalize separators so the assertion is OS-independent (Windows uses \).
    assert slot.strategy_code_dir.replace("\\", "/").endswith("strategies/al_s1/current"), slot.strategy_code_dir
    assert str(config_dir) in slot.trial_params_path
