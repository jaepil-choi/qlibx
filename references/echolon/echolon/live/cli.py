"""`echolon deploy` CLI sub-app."""
import logging

import typer

from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig
from echolon.live.orchestrator.portfolio import PortfolioTradingRunner

logger = logging.getLogger(__name__)

deploy_app = typer.Typer(
    name="deploy",
    help="Run live portfolio trading.",
    no_args_is_help=True,
)


@deploy_app.command("portfolio")
def deploy_portfolio(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate schema + paths then exit"),
) -> None:
    """Run multi-slot portfolio live trading (scheduled continuous)."""
    portfolio_config = PortfolioDeployConfig.load(config)
    enabled = portfolio_config.get_enabled_slots()
    logger.info("Loaded portfolio config: %d enabled slots", len(enabled))

    if validate_only:
        logger.info("Validation complete — exiting (--validate-only)")
        return

    portfolio_runner = PortfolioTradingRunner(config=portfolio_config)
    try:
        portfolio_runner.run()
    except KeyboardInterrupt:
        logger.info("Portfolio deploy stopped by user")
    finally:
        portfolio_runner.stop()


@deploy_app.command("portfolio-cycle")
def deploy_portfolio_cycle(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
) -> None:
    """Run a single portfolio trading cycle (for testing)."""
    portfolio_config = PortfolioDeployConfig.load(config)
    portfolio_runner = PortfolioTradingRunner(config=portfolio_config)
    try:
        result = portfolio_runner.run_single_cycle()
        logger.info("Single portfolio cycle complete: status=%s", result.get("status"))
    finally:
        portfolio_runner.stop()
