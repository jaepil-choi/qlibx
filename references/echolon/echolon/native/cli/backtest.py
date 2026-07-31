"""`echolon backtest <strategy_dir>` — single-strategy backtest with workspace recovery.

Walks up from <strategy_dir> to find .echolon-workspace.json, recovers
the trading context (market, instrument, frequency, bar_size,
date_range, initial_capital), and runs the backtest. No CLI flags
required for the common case; flags override individual marker fields.

Distinct from `echolon backtest portfolio` (which is a sub-Typer at
echolon/backtest/cli.py for multi-slot portfolio runs).
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from echolon.native.workspace import find_workspace_root, read_marker, WorkspaceNotFoundError
from echolon.native.validation import validate_indicator_names, validate_strategy_dir


def _run_backtest(
    strategy_dir: Path,
    *,
    instrument: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: Optional[str] = None,
    frequency: Optional[str] = None,
    bar_size: Optional[str] = None,
    unsafe: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    paths_config: Optional[Path] = None,
) -> None:
    """Plain Python helper — same body as ``backtest_single`` but without
    typer ``OptionInfo`` defaults so it's callable from other CLI commands
    (e.g. ``hello``).

    ``verbose=True`` raises the echolon namespace logger to DEBUG and
    selects the ``debug`` run_context (per-bar Risk/Entry/Exit/Sizer
    trace). ``verbose=False`` selects the ``summary`` run_context — root
    INFO with bar-loop loggers demoted to WARNING, so the user gets the
    one-line Sharpe summary without thousands of per-bar lines.
    """
    import logging
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    if verbose:
        os.environ.setdefault("ECHOLON_DEBUG_MODULES", "echolon.*")
        logging.getLogger("echolon").setLevel(logging.DEBUG)
    # Recover ctx from marker if available.
    ws_root: Optional[Path] = None
    try:
        ws_root = find_workspace_root(strategy_dir)
        marker = read_marker(ws_root)
        if not json_output:
            typer.echo(f"[ECHOLON] Workspace: {ws_root}")
    except WorkspaceNotFoundError:
        marker = {}
        if not json_output:
            typer.echo(
                "[ECHOLON] No workspace marker found; using CLI flags only. "
                "Tip: run `echolon init` to set up a workspace.",
                err=True,
            )

    market = market or marker.get("market")
    # Prefer the FULL instrument name ('aluminum') over the short code ('al') —
    # the indicator processor + data loader + market_data layout all use the
    # full name (e.g. {indicators_backtest_dir}/{instrument}/, and
    # {market_data_dir}/{MARKET}/{instrument}/main_contract.csv). The short
    # code is only used for the raw extractor source tree at
    # {raw_data_dir}/{market}/{instrument_code}/{minute_data,sort_by_date.csv}.
    instrument = instrument or marker.get("instrument") or marker.get("instrument_code")
    start = start or (marker.get("date_range") or [None, None])[0]
    end = end or (marker.get("date_range") or [None, None])[1]
    frequency = frequency or marker.get("frequency", "interday")
    bar_size = bar_size or marker.get("bar_size", "1d")

    missing = [n for n, v in [("market", market), ("instrument", instrument),
                              ("start", start), ("end", end)] if v is None]
    if missing:
        typer.echo(
            f"Missing context fields: {missing}. Either run from a workspace "
            f"(produced by `echolon init`) or pass the flags explicitly.",
            err=True,
        )
        raise typer.Exit(2)

    if not unsafe:
        errors = []
        errors.extend(validate_strategy_dir(strategy_dir))
        errors.extend(validate_indicator_names(strategy_dir))
        if errors:
            if not json_output:
                typer.echo(f"Validation failed with {len(errors)} error(s):")
                for e in errors:
                    typer.echo(str(e))
            else:
                import json as _json
                _json.dump({
                    "ok": False,
                    "validation_errors": [str(e) for e in errors],
                }, sys.stdout, indent=2)
                sys.stdout.write("\n")
            raise typer.Exit(1)
        if not json_output:
            typer.echo("✓ Validation passed.")

    # Thread workspace as ECHOLON_PROJECT_ROOT so PathsConfig.from_env() resolves
    # defaults relative to the workspace (only used when no marker overrides
    # and no --paths-config flag).
    if ws_root is not None:
        os.environ["ECHOLON_PROJECT_ROOT"] = str(ws_root)

    from echolon.config.paths_config import PathsConfig
    from echolon import quick_start

    # Path-config resolution order (most explicit wins):
    #   1. --paths-config <file.json>  (CLI flag, this run only)
    #   2. workspace marker's `paths` overrides (set by `echolon init`/`hello`)
    #   3. PathsConfig.from_env() (ECHOLON_PROJECT_ROOT or cwd)
    paths: Optional[PathsConfig] = None
    if paths_config is not None:
        paths = PathsConfig.from_file(paths_config)
        if not json_output:
            typer.echo(f"[ECHOLON] Paths from --paths-config: {paths_config}")
    else:
        paths_overrides_raw = marker.get("paths") if marker else None
        if paths_overrides_raw and ws_root is not None:
            valid_fields = set(PathsConfig.model_fields.keys())
            overrides_abs = {
                k: ws_root / v
                for k, v in paths_overrides_raw.items()
                if k in valid_fields
            }
            paths = PathsConfig.from_project_root(ws_root, **overrides_abs)
    from echolon.backtest.engine.backtest_runner import BacktestRunner, _RunnerConfig
    from echolon.indicators.run import run_indicator_calculation
    from echolon.strategy.loader import StrategyLoader

    if paths is None:
        paths = PathsConfig.from_env()

    qs = quick_start(
        market=market, instrument=instrument,
        start_date=start, end_date=end,
        frequency=frequency, bar_size=bar_size,
    )
    ctx = qs[0]
    bt_cfg = qs[1]
    # Pin paths explicitly to PathsConfig so they don't depend on cwd or
    # quick_start's defaults.
    bt_cfg.strategy_dir = strategy_dir.resolve()
    bt_cfg.indicator_dir = paths.indicators_backtest_dir
    bt_cfg.market_data_dir = paths.market_data_dir

    # `strategy_code_dir` triggers slot-style indicator layout:
    # {indicators_backtest_dir}/{slot_name}/{strategy_indicators.csv,by_contract/}
    # where slot_name = Path(strategy_code_dir).name (e.g. "baseline").
    slot_name = strategy_dir.name
    slot_indicator_dir = paths.indicators_backtest_dir / slot_name

    # Compute indicators if missing.
    indicators_csv = slot_indicator_dir / "strategy_indicators.csv"
    if not indicators_csv.exists():
        if not json_output:
            typer.echo(f"[ECHOLON] Computing indicators (first run for this workspace)…")
        ind_list_path = strategy_dir / "strategy_indicator_list.json"
        if not ind_list_path.is_file():
            cands = list(strategy_dir.glob("*indicator*list*.json"))
            if not cands:
                typer.echo(
                    f"No strategy_indicator_list.json under {strategy_dir}.",
                    err=True,
                )
                raise typer.Exit(2)
            ind_list_path = cands[0]
        indicator_list = json.loads(ind_list_path.read_text())
        run_indicator_calculation(
            ctx=ctx,
            output_dir=str(slot_indicator_dir),
            indicator_list=indicator_list,
            use_parallel=False,
            start_date=start,
            end_date=end,
            paths=paths,
        )

    if not json_output:
        typer.echo(f"[ECHOLON] Running backtest: {strategy_dir.name} ({instrument} {start}..{end})")

    # Pin the runner's internal path config to our resolved PathsConfig so
    # the marker.paths overrides (workspace/indicators, data/) actually win.
    runner_cfg = _RunnerConfig(
        indicator_dir=str(paths.indicators_backtest_dir),
        market_data_dir=str(paths.market_data_dir),
        backtest_results_dir=str(paths.backtest_results_dir),
    )
    runner = BacktestRunner(
        ctx=ctx,
        paths=paths,
        config=runner_cfg,
        strategy_code_dir=str(strategy_dir.resolve()),
        backtest_config=bt_cfg,
    )
    runner.load_data()
    loader = StrategyLoader(strategy_dir.resolve())
    default_params = loader.load_attr("strategy_params", "DEFAULT_PARAMS")
    try:
        result = runner.run(default_params, context='debug' if verbose else 'summary')
    except Exception as exc:
        # Emit informative output on backtest failure. In --json mode, this is
        # what an LLM agent reads to decide whether to retry / change params.
        if json_output:
            import json as _json
            _json.dump({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "strategy_dir": str(strategy_dir.resolve()),
                "context": {
                    "market": market, "instrument": instrument,
                    "start": start, "end": end,
                    "frequency": frequency, "bar_size": bar_size,
                },
            }, sys.stdout, indent=2)
            sys.stdout.write("\n")
            raise typer.Exit(1)
        # In human-readable mode, re-raise so the user sees the stack trace.
        # (Hello catches this; standalone `echolon backtest` lets it propagate.)
        raise

    # ``runner.run`` returns a flat metrics dict at the top level — keys
    # like sharpe_ratio_annual / total_return_pct / max_drawdown_pct (already
    # in percent) / total_trades.
    metrics = result if isinstance(result, dict) else {}
    if json_output:
        import json as _json
        _json.dump({
            "ok": True,
            "sharpe": metrics.get("sharpe_ratio_annual"),
            "max_drawdown": metrics.get("max_drawdown_pct"),
            "annual_return": metrics.get("total_return_pct"),
            "win_rate": metrics.get("win_rate_pct"),
            "total_trades": metrics.get("total_trades"),
            "profit_factor": metrics.get("profit_factor"),
            "trades_per_week": metrics.get("trades_per_week"),
            "strategy_dir": str(strategy_dir.resolve()),
            "context": {
                "market": market, "instrument": instrument,
                "start": start, "end": end,
                "frequency": frequency, "bar_size": bar_size,
            },
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sharpe = metrics.get("sharpe_ratio_annual")
        max_dd_pct = metrics.get("max_drawdown_pct")
        ann_ret_pct = metrics.get("total_return_pct")
        n_trades = metrics.get("total_trades", 0)
        sharpe_str = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
        max_dd_str = f"{max_dd_pct:.1f}%" if isinstance(max_dd_pct, (int, float)) else str(max_dd_pct)
        ret_str = f"{ann_ret_pct:.2f}%" if isinstance(ann_ret_pct, (int, float)) else str(ann_ret_pct)
        typer.echo(
            f"[ECHOLON] ✓ Sharpe: {sharpe_str} | Return: {ret_str} | "
            f"MaxDD: {max_dd_str} | {n_trades} trades"
        )


def backtest_single(
    strategy_dir: Path = typer.Argument(..., help="Strategy directory (under a workspace with .echolon-workspace.json)"),
    instrument: Optional[str] = typer.Option(None, "--instrument", help="Override workspace marker's instrument"),
    start: Optional[str] = typer.Option(None, "--start", help="Override marker start date"),
    end: Optional[str] = typer.Option(None, "--end", help="Override marker end date"),
    market: Optional[str] = typer.Option(None, "--market", help="Override marker market"),
    frequency: Optional[str] = typer.Option(None, "--frequency"),
    bar_size: Optional[str] = typer.Option(None, "--bar-size"),
    unsafe: bool = typer.Option(False, "--unsafe", help="Skip pre-validation"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON metrics (for LLM agents)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-bar Risk/Entry/Exit/Sizer trace. Default emits a one-line summary only."),
    paths_config: Optional[Path] = typer.Option(
        None, "--paths-config",
        help="JSON file with PathsConfig overrides (must include 'project_root'). "
             "Beats the workspace marker; relative paths resolve against the JSON file's dir.",
    ),
) -> None:
    """Run a backtest, recovering ctx from the workspace marker file.

    Output modes:
    - default: human-readable progress + summary line.
    - --json: a single JSON object on stdout with keys
      ``{sharpe, max_drawdown, total_trades, annual_return, win_rate, ...}``.
    - --verbose: show per-bar component trace.
    - --paths-config <file>: hand-edited JSON config overrides workspace
      marker paths.
    """
    _run_backtest(
        strategy_dir=strategy_dir,
        instrument=instrument, start=start, end=end, market=market,
        frequency=frequency, bar_size=bar_size,
        unsafe=unsafe, json_output=json_output, verbose=verbose,
        paths_config=paths_config,
    )
