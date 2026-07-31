"""`echolon hello` — out-of-the-box demo.

Internally: delegate to `echolon init` (akshare download + scaffold) →
run backtest. Requires network on first run; ~30 seconds.
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

import typer

DEMO_DIR_NAME = "echolon-hello"


def hello_command(
    instrument: str = typer.Option("aluminum", "--instrument",
                                   help="SHFE instrument name (e.g. aluminum, copper)"),
    template: str = typer.Option("momentum_breakout", "--template",
                                  help="Template to scaffold under strategy/baseline/. "
                                       "Default 'momentum_breakout' produces actual trades on the demo data; "
                                       "'minimal' is hold-forever (educational, no trades)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing ./echolon-hello/"),
) -> None:
    """Akshare-driven instant demo. Lays a workspace, scaffolds a strategy,
    runs a backtest."""

    # Pre-flight ta-lib (the indicator pipeline imports talib).
    try:
        import talib  # noqa: F401
    except ImportError:
        from echolon.native.cli.doctor import _check_talib
        check = _check_talib()
        typer.echo(f"[ECHOLON] {check['detail']}", err=True)
        if check.get("hint"):
            for line in check["hint"].splitlines():
                typer.echo(f"[ECHOLON]   {line}", err=True)
        raise typer.Exit(3)

    cwd = Path.cwd().resolve()
    home = Path(os.environ.get("HOME", str(Path.home()))).resolve()
    if cwd == home:
        typer.echo("Refusing to create demo at $HOME. cd into a project dir first.", err=True)
        raise typer.Exit(2)
    if cwd == Path("/"):
        typer.echo("Refusing to create demo at /.", err=True)
        raise typer.Exit(2)

    demo = cwd / DEMO_DIR_NAME
    if demo.exists():
        if not force:
            typer.echo(
                f"./{DEMO_DIR_NAME}/ already exists. Pass --force to overwrite.",
                err=True,
            )
            raise typer.Exit(2)
        shutil.rmtree(demo)

    # Compute a 2-year window ending today so we have enough data for the
    # default backtest window.
    from datetime import date, timedelta
    end_date = date.today()
    start_date = end_date - timedelta(days=730)

    # Delegate to init's plain-Python implementation (skips typer Option defaults).
    from echolon.native.cli.init import _init_impl
    typer.echo(f"[ECHOLON] Downloading {instrument} data via akshare...")
    _init_impl(
        target=demo,
        template=template,
        market="SHFE",
        instrument=instrument,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        initial_capital=200000.0,
        force=False,
    )

    # Run backtest immediately so the user sees a number.
    typer.echo(f"[ECHOLON] Running backtest...")
    strategy_root = demo / "strategy" / "baseline"
    from echolon.native.cli.backtest import _run_backtest
    try:
        _run_backtest(strategy_dir=strategy_root)
    except typer.Exit as e:
        if e.exit_code != 0:
            typer.echo(f"[ECHOLON] (Backtest exited {e.exit_code} — see output above.)")
    except Exception as exc:
        typer.echo(f"[ECHOLON] Backtest raised: {type(exc).__name__}: {exc}")
        typer.echo(f"[ECHOLON] (Pipeline completed; the chosen template may not "
                   f"produce trades on this window. Try editing "
                   f"./{demo.name}/strategy/baseline/entry.py.)")

    typer.echo("")
    typer.echo(f"[ECHOLON] Backtest artifacts: ./{demo.name}/workspace/backtest/")
    typer.echo(f"[ECHOLON] Try editing ./{demo.name}/strategy/baseline/entry.py and re-running:")
    typer.echo(f"[ECHOLON]   echolon backtest single ./{demo.name}/strategy/baseline/")
