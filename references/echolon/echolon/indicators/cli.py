"""echolon indicators CLI — list capabilities."""
from __future__ import annotations

import json

import typer

from echolon.indicators.calculators.interday import indicator_mapping as interday_mapping
from echolon.indicators.calculators.intraday import indicator_mapping as intraday_mapping

indicators_app = typer.Typer(
    name="indicators",
    help="Indicator library utilities (list, doc).",
    no_args_is_help=True,
)


@indicators_app.command("list")
def indicators_list(
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    """Dump the library's indicator capabilities.

    The output is a mapping `indicator_name -> param_info_dict` — useful as
    a starting template for your own `indicator_list` config.
    """
    catalog = _build_catalog()
    if format == "json":
        typer.echo(json.dumps(catalog, indent=2))
    else:
        typer.echo(f"Echolon knows how to compute {len(catalog)} indicators:")
        for name, info in sorted(catalog.items()):
            typer.echo(f"  {name}: {info}")


def _build_catalog() -> dict:
    """Return mapping of indicator_name -> metadata dict.

    Each entry has:
      - ``has_lookback``: True if the indicator has a period-like parameter
        (sweepable single-dim lookback).
      - ``function``: the underlying calculator function name
      - ``frequencies``: list of supported frequencies ("interday", "intraday", or both)

    Useful as a discovery tool and starting template for building your own
    ``indicator_list`` config.
    """
    from echolon.indicators import catalog as _meta_catalog

    catalog: dict[str, dict] = {}

    # Walk interday mapping
    for name, entry in interday_mapping.PER_CONTRACT_TALIB_MAP.items():
        info = _meta_catalog.info(name.lower())
        catalog[name] = {
            "has_lookback": info.has_lookback if info else False,
            "function": entry["function"],
            "frequencies": ["interday"],
        }

    # Walk intraday mapping — merge if already present from interday
    for name, entry in intraday_mapping.INTRADAY_INDICATOR_MAPPING.items():
        if name in catalog:
            # Indicator exists in both frequencies
            catalog[name]["frequencies"] = ["interday", "intraday"]
        else:
            info = _meta_catalog.info(name.lower())
            catalog[name] = {
                "has_lookback": info.has_lookback if info else False,
                "function": entry["function"],
                "frequencies": ["intraday"],
            }

    return catalog
