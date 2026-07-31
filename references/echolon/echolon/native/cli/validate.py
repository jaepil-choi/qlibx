"""`echolon validate <dir>` — check a strategy directory."""

import json as _json
from pathlib import Path

import typer

from echolon.native.validation import (
    validate_indicator_names,
    validate_strategy_dir,
)


def validate_command(
    strategy_dir: Path = typer.Argument(..., help="Path to strategy directory"),
    json: bool = typer.Option(False, "--json", help="Output JSON (for agents)"),
) -> None:
    """Validate a strategy directory against Echolon contracts."""
    errors = []
    errors.extend(validate_strategy_dir(strategy_dir))
    errors.extend(validate_indicator_names(strategy_dir))

    if json:
        _print_json(errors)
    else:
        _print_human(strategy_dir, errors)

    raise typer.Exit(code=0 if not errors else 1)


def _print_json(errors: list) -> None:
    payload = {
        "status": "ok" if not errors else "failed",
        "errors": [
            {
                "code": e.code,
                "what": e.what,
                "why": e.why,
                "fix": e.fix,
                "context": e.context,
                "docs_url": e.docs_url,
            }
            for e in errors
        ],
        "warnings": [],
    }
    typer.echo(_json.dumps(payload, indent=2))


def _print_human(strategy_dir: Path, errors: list) -> None:
    typer.echo(f"Validating {strategy_dir}...")
    if not errors:
        typer.echo("✓ Strategy directory is valid.")
        return
    for err in errors:
        typer.echo(str(err))
    typer.echo(f"\nSummary: {len(errors)} error(s). Fix and re-run `echolon validate`.")
