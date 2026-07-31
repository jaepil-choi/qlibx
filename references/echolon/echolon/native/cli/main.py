"""Echolon CLI — `echolon <command>` entry point."""

import typer

from echolon.backtest.cli import backtest_app
from echolon.live.cli import deploy_app
from echolon.native.cli import backtest as backtest_cmd
from echolon.native.cli import doctor as doctor_cmd
from echolon.native.cli import examples as examples_cmd
from echolon.native.cli import hello as hello_cmd
from echolon.native.cli import init as init_cmd
from echolon.native.cli import migrate as migrate_cmd
from echolon.native.cli import schema as schema_cmd
from echolon.native.cli import validate as validate_cmd

app = typer.Typer(
    name="echolon",
    help="Echolon — strategy backtesting framework. See `echolon hello` to get started.",
    no_args_is_help=False,  # we override with our own welcome below
)


@app.callback(invoke_without_command=True)
def _callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit"),
) -> None:
    """Echolon CLI — multi-command entry point."""
    # Force UTF-8 stdout/stderr so Unicode glyphs (✓, →, em-dashes, Chinese
    # in user-supplied symbols, etc.) round-trip on every platform. Windows
    # consoles default to cp1252 and would otherwise raise UnicodeEncodeError
    # on the first emoji or arrow we print. errors="replace" is a defensive
    # backstop for the rare case a downstream pipe is locked to a narrower
    # encoding — the message gets a `?` instead of a crash.
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()

    if version:
        from echolon import __version__
        typer.echo(f"echolon {__version__}")
        raise typer.Exit(0)

    if ctx.invoked_subcommand is None:
        typer.echo("Echolon — strategy backtesting framework, LLM-agent friendly.")
        typer.echo("")
        typer.echo("Get started:")
        typer.echo("  echolon hello                                   # 30s demo with bundled SHFE aluminum data")
        typer.echo("  echolon init <workspace> --market SHFE \\")
        typer.echo("                            --instrument <i> --start <d> --end <d>")
        typer.echo("                                                  # start a real project (downloads data via akshare)")
        typer.echo("  echolon backtest single <strategy_dir>          # iterate after editing strategy code")
        typer.echo("")
        typer.echo("More: echolon --help  |  echolon <command> --help")


from echolon.indicators.cli import indicators_app

app.command(name="hello")(hello_cmd.hello_command)
app.command(name="doctor")(doctor_cmd.doctor_command)
app.command(name="validate")(validate_cmd.validate_command)
app.command(name="init")(init_cmd.init_command)
app.command(name="schema")(schema_cmd.schema_command)
app.command(name="migrate")(migrate_cmd.migrate_command)
app.add_typer(examples_cmd.examples_app, name="examples")
app.add_typer(deploy_app, name="deploy")

# Register `backtest single <dir>` as a sub-command alongside the existing
# `backtest portfolio` (defined in echolon/backtest/cli.py). For the natural
# `echolon backtest <dir>` form, see `echolon backtest single <dir>` — same
# implementation, predictable parsing.
backtest_app.command(name="single")(backtest_cmd.backtest_single)
app.add_typer(backtest_app, name="backtest")
app.add_typer(indicators_app, name="indicators")


if __name__ == "__main__":
    app()
