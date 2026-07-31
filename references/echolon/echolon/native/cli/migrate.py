"""`echolon migrate <codebase>` — rewrite imports from old echolon layout to new."""

import re
from pathlib import Path

import typer


# Old import path → new import path. Ordered longest-first when applied to avoid
# prefix collisions (e.g., quant_engine.backtest.optimization before quant_engine.backtest).
IMPORT_MIGRATIONS: dict[str, str] = {
    # ---- errors (promoted to root) ----
    "echolon.native.validation.errors": "echolon.errors",
    # ---- types.py → strategy.schemas ----
    "echolon.quant_engine.types": "echolon.strategy.schemas",
    # ---- core/base → strategy/ ----
    "echolon.quant_engine.core.base.base_strategy": "echolon.strategy.base",
    "echolon.quant_engine.core.base.base_component": "echolon.strategy.component",
    "echolon.quant_engine.core.base.parameter_architecture": "echolon.strategy.parameter_architecture",
    "echolon.quant_engine.core.base.state_manager": "echolon.strategy.state_manager",
    "echolon.quant_engine.core.base.hooks": "echolon.strategy.hooks",
    "echolon.quant_engine.core.frequency": "echolon.strategy.frequency",
    "echolon.quant_engine.core.interfaces.trading_interfaces": "echolon.strategy.interfaces",
    "echolon.quant_engine.core.interfaces.frequency_context": "echolon.strategy.frequency.interface",
    "echolon.quant_engine.core.interfaces.session_context": "echolon.strategy.frequency.session_interface",
    "echolon.quant_engine.core.interfaces.market_adapter": "echolon.markets.interface",
    "echolon.quant_engine.core.logging.strategy_logger": "echolon.strategy.logging",
    # ---- strategy loader / generators ----
    "echolon.quant_engine.strategy.loader": "echolon.strategy.loader",
    "echolon.quant_engine.strategy.generators": "echolon.strategy.generators",
    # ---- backtest/engine subfolder moves ----
    "echolon.quant_engine.backtest.engine.analyzers": "echolon.backtest.metrics.analyzers",
    # ---- backtest/ promoted ----
    "echolon.quant_engine.backtest.portfolio_backtest_runner": "echolon.backtest.portfolio_runner",
    "echolon.quant_engine.backtest.portfolio_metrics": "echolon.backtest.metrics.portfolio_metrics",
    "echolon.quant_engine.backtest": "echolon.backtest",
    "echolon.quant_engine.engine_factory": "echolon.engine.factory",
    "echolon.quant_engine.run_backtest": "echolon.backtest.runner",
    "echolon.quant_engine.reporting": "echolon.backtest.metrics.reporting",
    "echolon.quant_engine.calculate_mfe_mae": "echolon.backtest.metrics.mfe_mae",
    "echolon.quant_engine.logging_utils": "echolon.backtest.logging_utils",
    # ---- quant_engine/schemas consolidated ----
    "echolon.quant_engine.schemas.backtest_results": "echolon.backtest.schemas",
    "echolon.quant_engine.schemas.trade_log": "echolon.backtest.schemas",
    "echolon.quant_engine.schemas.strategy_log": "echolon.backtest.schemas",
    "echolon.quant_engine.schemas.selected_trial": "echolon.backtest.schemas",
    "echolon.quant_engine.schemas": "echolon.backtest.schemas",
    # ---- data_loader (merged into data/loaders) ----
    "echolon.quant_engine.data_loader.SHFE_loader": "echolon.data.loaders.backtest_data_loader",
    "echolon.quant_engine.data_loader.contract_data": "echolon.data.loaders.contract_loader",
    "echolon.quant_engine.data_loader": "echolon.data.loaders",
    # ---- deploy → live ----
    "echolon.quant_engine.deploy.engine.portfolio_trading_runner": "echolon.live.orchestrator.portfolio",
    "echolon.quant_engine.deploy.engine.capital_slot": "echolon.live.slot.capital_slot",
    "echolon.quant_engine.deploy.engine.trading_slot": "echolon.live.slot.trading_slot",
    "echolon.quant_engine.deploy.engine.slot_aware_portfolio": "echolon.live.slot.slot_aware_portfolio",
    "echolon.quant_engine.deploy.engine.trading_data_logger": "echolon.live.io.data_logger",
    "echolon.quant_engine.deploy.engine.dashboard_aggregator": "echolon.live.io.kpi_aggregator",
    "echolon.quant_engine.deploy.engine.dashboard_data_generator": "echolon.live.io.kpi_aggregator",
    "echolon.quant_engine.deploy.engine.dashboard_data_sender": "echolon.live.io.kpi_aggregator",
    "echolon.quant_engine.deploy.engine.portfolio_risk_overlay": "echolon.live.slot.risk_overlay",
    "echolon.quant_engine.deploy.data_pipeline.trading_util": "echolon.data.loaders.contract_loader",
    "echolon.quant_engine.deploy.config": "echolon.live.config",
    "echolon.quant_engine.deploy.platforms": "echolon.live.platforms",
    "echolon.quant_engine.deploy": "echolon.live",
    # ---- market_adapters → markets ----
    "echolon.quant_engine.market_adapters.shfe.shfe_adapter": "echolon.markets.shfe.adapter",
    "echolon.quant_engine.market_adapters.shfe.shfe_session_provider": "echolon.markets.shfe.sessions",
    "echolon.quant_engine.market_adapters.shfe": "echolon.markets.shfe",
    "echolon.quant_engine.market_adapters.crypto.crypto_adapter": "echolon.markets.crypto.adapter",
    "echolon.quant_engine.market_adapters.crypto.crypto_session_provider": "echolon.markets.crypto.sessions",
    "echolon.quant_engine.market_adapters.crypto": "echolon.markets.crypto",
    "echolon.quant_engine.market_adapters.base_adapter": "echolon.markets.base",
    "echolon.quant_engine.market_adapters": "echolon.markets",
    # ---- data_pipeline → data ----
    "echolon.data_pipeline.run_pipeline": "echolon.data.backtest_data",
    "echolon.data_pipeline.schemas.ohlcv": "echolon.data.schemas",
    "echolon.data_pipeline.schemas.standard_schema": "echolon.data.schemas",
    "echolon.data_pipeline": "echolon.data",
    # ---- indicators run renamed ----
    "echolon.indicators.run_indicators": "echolon.indicators.run",
    # ---- config merge ----
    "echolon.config.quant_engine": "echolon.config.settings",
}


def _rewrite_content(content: str, migrations: dict[str, str]) -> str:
    """Apply all migration rules to content, longest-old-path first."""
    sorted_mappings = sorted(migrations.items(), key=lambda kv: -len(kv[0]))

    for old, new in sorted_mappings:
        old_escaped = re.escape(old)
        # Match: (from|import) <old>  with a lookahead for end-of-identifier so
        # we don't consume the trailing char (dot/space/eol) in the substitution.
        pattern = re.compile(
            rf"(?P<prefix>(?:from|import)\s+){old_escaped}(?=\.|\s|$)",
            re.MULTILINE,
        )
        content = pattern.sub(
            lambda m: f"{m.group('prefix')}{new}",
            content,
        )
    return content


def _migrate_file(path: Path, dry_run: bool) -> bool:
    """Rewrite one .py file. Returns True if changes were made."""
    try:
        original = path.read_text()
    except (UnicodeDecodeError, PermissionError):
        return False

    new = _rewrite_content(original, IMPORT_MIGRATIONS)
    if new == original:
        return False

    if not dry_run:
        path.write_text(new)
    return True


def migrate_command(
    target: Path = typer.Argument(..., help="Path to codebase to migrate"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print each file changed"),
) -> None:
    """Rewrite old echolon imports to new layout (v0.1.0)."""
    if not target.is_dir():
        typer.echo(f"Not a directory: {target}")
        raise typer.Exit(code=2)

    changed = []
    for py_file in target.rglob("*.py"):
        # Skip common junk dirs
        if any(part in py_file.parts for part in ("__pycache__", ".git", ".venv", "node_modules")):
            continue
        if _migrate_file(py_file, dry_run):
            changed.append(py_file)
            if verbose:
                typer.echo(f"[changed] {py_file}")

    action = "Would update" if dry_run else "Updated"
    typer.echo(f"\n{action} {len(changed)} file(s).")
    if dry_run and changed:
        typer.echo("Run without --dry-run to apply.")
