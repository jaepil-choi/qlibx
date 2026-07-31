"""`echolon schema <type>` — dump Pydantic JSON schema."""

import json as _json
from typing import Optional

import typer

from echolon.config.backtest_config import BacktestConfig
from echolon.config.indicator_config import IndicatorConfig
from echolon.config.optuna_config import OptunaConfig


_EXPORTABLE = {
    "BacktestConfig": BacktestConfig,
    "OptunaConfig": OptunaConfig,
    "IndicatorConfig": IndicatorConfig,
}


def schema_command(
    type_name: Optional[str] = typer.Argument(None, help="Pydantic type name"),
    list_types: bool = typer.Option(False, "--list", help="List all exportable types"),
) -> None:
    """Dump Pydantic JSON schemas for agent introspection."""
    if list_types or type_name is None:
        typer.echo("Exportable types:")
        for name in _EXPORTABLE:
            typer.echo(f"  {name}")
        return

    if type_name not in _EXPORTABLE:
        typer.echo(f"Unknown type: {type_name}")
        typer.echo(f"Available: {', '.join(_EXPORTABLE)}")
        raise typer.Exit(code=2)

    schema = _EXPORTABLE[type_name].model_json_schema()
    typer.echo(_json.dumps(schema, indent=2))
