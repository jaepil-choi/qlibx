"""`echolon backtest` CLI sub-app."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from echolon.backtest.portfolio_runner import PortfolioBacktestRunner, _make_serializable
from echolon.config.backtest_config import BacktestConfig
from echolon.config.optuna_config import OptunaConfig
from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig

logger = logging.getLogger(__name__)

backtest_app = typer.Typer(
    name="backtest",
    help="Backtest strategies (portfolio or single-instrument).",
    no_args_is_help=True,
)


@backtest_app.command("portfolio")
def backtest_portfolio(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
    output_dir: str = typer.Option("./workspace/portfolio_backtest", "--output-dir", "-o"),
    start_date: str = typer.Option(..., "--start", help="YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end", help="YYYY-MM-DD"),
    market_data_dir: str = typer.Option("./dataset", "--market-data-dir"),
    indicator_dir: str = typer.Option("./workspace/data/indicators/backtest", "--indicator-dir"),
    strategy_dir: str = typer.Option("", "--strategy-dir",
        help="Optional; defaults to the config file's directory."),
    skip_per_window: bool = typer.Option(False, "--skip-per-window",
        help="Skip fresh-capital per-year breakdown"),
) -> None:
    """Run portfolio backtest — continuous + (optional) per-window fresh-capital windows."""
    portfolio_config = PortfolioDeployConfig.load(config)
    enabled = portfolio_config.get_enabled_slots()
    logger.info("Loaded portfolio config: %d enabled slots", len(enabled))

    # Default strategy_dir to the config file's directory (slots have per-slot paths)
    if not strategy_dir:
        strategy_dir = str(Path(config).resolve().parent)

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    backtest_config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        strategy_dir=Path(strategy_dir),
        market_data_dir=Path(market_data_dir),
        indicator_dir=Path(indicator_dir),
        results_dir=Path(output_dir),
    )
    optuna_config = OptunaConfig()

    backtest_runner = PortfolioBacktestRunner(
        portfolio_config,
        output_dir=output_dir,
        backtest_config=backtest_config,
        optuna_config=optuna_config,
    )
    results = backtest_runner.run(start_date=start_date, end_date=end_date)

    window_results = {"windows": []}
    if not skip_per_window:
        window_results = backtest_runner.run_per_window()

    all_results = {**results, "window_backtests": window_results}
    metrics_path = Path(output_dir) / "portfolio_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(_make_serializable(all_results), f, indent=2, default=str)

    pm = results.get("portfolio_metrics", {})
    typer.echo("=" * 70)
    typer.echo(
        f"Portfolio backtest complete — "
        f"Sharpe={pm.get('sharpe_ratio', 0):.4f} "
        f"Annual={pm.get('annual_return', 0) * 100:.2f}% "
        f"MaxDD={pm.get('max_drawdown', 0) * 100:.2f}%"
    )
    typer.echo(f"Output: {metrics_path}")
