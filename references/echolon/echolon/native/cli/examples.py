"""`echolon examples` — bundled example strategies."""

import shutil
from pathlib import Path

import typer

from echolon.native.examples_registry import AVAILABLE_EXAMPLES, example_path


examples_app = typer.Typer(name="examples", help="Manage bundled example strategies.")


# One-line descriptions per template — surfaced on `echolon examples --list`
# so users (and LLM agents) can pick a starting point at a glance.
_TEMPLATE_BLURBS = {
    "minimal": "Empty stubs returning hold-forever outputs. Smallest possible strategy.",
    "momentum_breakout": "20-bar Donchian breakout entry, ATR-trailing exit. Trades on demo data.",
    "rsi_mean_reversion": "RSI(14) entry below 30 (LONG) / above 70 (SHORT) with time exit.",
}


@examples_app.callback(invoke_without_command=True)
def examples_main(
    ctx: typer.Context,
    list_examples: bool = typer.Option(False, "--list", help="List all examples"),
) -> None:
    """List or copy bundled Echolon examples."""
    if ctx.invoked_subcommand is not None:
        return
    if list_examples:
        typer.echo("Available templates:")
        for name in AVAILABLE_EXAMPLES:
            blurb = _TEMPLATE_BLURBS.get(name, "")
            typer.echo(f"  {name:<24} {blurb}")
        typer.echo("")
        typer.echo("Use these from `echolon init <dir> --template <name>` "
                   "or `echolon hello --template <name>`.")
        return
    typer.echo("Use --list to see examples, or `copy <name> <dest>` to copy one.")


@examples_app.command("copy")
def copy_example(
    name: str = typer.Argument(..., help="Example name"),
    dest: Path = typer.Argument(..., help="Destination directory"),
) -> None:
    """Copy a bundled example to dest."""
    if name not in AVAILABLE_EXAMPLES:
        typer.echo(f"Unknown example: {name}")
        raise typer.Exit(code=2)

    if dest.exists() and any(dest.iterdir()):
        typer.echo(f"Destination exists and is not empty: {dest}")
        raise typer.Exit(code=2)

    src = example_path(name)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    typer.echo(f"✓ Copied {name} to {dest}")
