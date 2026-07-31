"""`echolon init <dir>` — scaffold a strategy, with optional full-workspace setup.

Two modes, distinguished by whether market/data flags are provided:

1. **Template-only** (no market/data flags)::

       echolon init my-strategy --template minimal

   Just copies a bundled template into the target dir. Same as
   ``echolon examples copy <template> <dir>``.

2. **Full workspace** (market/instrument/dates supplied)::

       echolon init my-zinc --market SHFE --instrument zinc \\
                            --start 2022-01-01 --end 2024-12-31 \\
                            --template minimal

   Creates a workspace with downloaded data (via akshare), a
   ``main_contract.csv`` derived from per-contract volume, a scaffolded
   strategy under ``strategy/baseline/``, and a ``.echolon-workspace.json``
   marker for ``echolon backtest`` to find later.
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Optional

import typer

from echolon.native.templates import AVAILABLE_TEMPLATES, template_path
from echolon.native.workspace import write_marker


def init_command(
    target_dir: Path = typer.Argument(..., help="Target directory (workspace or strategy)"),
    template: str = typer.Option("minimal", "--template", "-t",
                                  help=f"Strategy template. Available: {AVAILABLE_TEMPLATES}"),
    # Full-init flags (all optional — when absent, runs in template-only mode).
    market: Optional[str] = typer.Option(None, "--market", help="Market (e.g. SHFE)"),
    instrument: Optional[str] = typer.Option(None, "--instrument", help="Instrument name (e.g. aluminum, zinc)"),
    start: Optional[str] = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: Optional[str] = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    initial_capital: float = typer.Option(200000.0, "--initial-capital"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing target"),
) -> None:
    target = target_dir
    return _init_impl(
        target=target, template=template,
        market=market, instrument=instrument, start=start, end=end,
        initial_capital=initial_capital, force=force,
    )


def _init_impl(
    *,
    target: Path,
    template: str,
    market: Optional[str],
    instrument: Optional[str],
    start: Optional[str],
    end: Optional[str],
    initial_capital: float,
    force: bool,
) -> None:
    """Scaffold a strategy. With --market/--instrument/--start/--end, also
    create a full workspace with downloaded data."""

    if template not in AVAILABLE_TEMPLATES:
        typer.echo(f"Unknown template: {template}; available: {AVAILABLE_TEMPLATES}", err=True)
        raise typer.Exit(2)

    full_init_flags = [market, instrument, start, end]
    n_full_flags = sum(1 for f in full_init_flags if f is not None)
    if n_full_flags not in (0, 4):
        typer.echo(
            "Full-init requires all of --market / --instrument / --start / --end "
            "or none of them.", err=True,
        )
        raise typer.Exit(2)

    is_full_init = n_full_flags == 4

    # Pre-flight ta-lib for full-init (indicator pipeline imports talib).
    if is_full_init:
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

    # Safety guards apply only to full-init (template-only is just a copy).
    if is_full_init:
        cwd = Path.cwd().resolve()
        home = Path(os.environ.get("HOME", str(Path.home()))).resolve()
        if cwd == home:
            typer.echo("Refusing to create a workspace at $HOME. cd into a project dir.", err=True)
            raise typer.Exit(2)
        if cwd == Path("/"):
            typer.echo("Refusing to create a workspace at /.", err=True)
            raise typer.Exit(2)

    target = target.resolve()
    if target.exists():
        if not force:
            typer.echo(f"{target} already exists. Pass --force to overwrite.", err=True)
            raise typer.Exit(2)
        shutil.rmtree(target)

    if not is_full_init:
        # Template-only mode: just copy a bundled template.
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(template_path(template), target, dirs_exist_ok=True)
        typer.echo(f"✓ Scaffolded {template} → {target}")
        typer.echo("Next: edit entry.py / exit.py / sizer.py and run `echolon validate <dir>` + `echolon backtest <dir>`.")
        return

    # Full-init mode.
    target.mkdir(parents=True, exist_ok=False)
    typer.echo(f"[ECHOLON] Creating workspace at {target}")

    from echolon.config.markets.factory import MarketFactory
    spec = MarketFactory.get_instrument_flexible(market, instrument)
    if spec is None:
        typer.echo(
            f"Unknown {market} instrument {instrument!r}. "
            f"Supported: {MarketFactory.list_instruments(market)}",
            err=True,
        )
        raise typer.Exit(2)
    instrument_code = spec.code

    # Test stub — bypass akshare entirely.
    test_stub = os.environ.get("ECHOLON_INIT_TEST_STUB") == "1"

    # Consolidated layout: data/{market}/{instrument}/ holds OHLCV
    # (sort_by_contract/, sort_by_date.csv, trading_calendar.csv) AND
    # main_contract.csv. Workspace marker records the corresponding
    # PathsConfig overrides so backtest/indicator paths stay workspace-local.
    instrument_data_root = target / "data" / market.upper() / instrument
    indicators_root = target / "workspace" / "indicators"

    if test_stub:
        typer.echo("[ECHOLON]   (test stub — skipping akshare)")
        _write_stub_data(instrument_data_root, instrument, instrument_code)
    elif market.upper() == "SHFE":
        # Friendly upfront check: if akshare isn't installed, tell the user
        # how to fix it.
        try:
            import akshare  # noqa: F401
        except ImportError:
            typer.echo(
                "[ECHOLON] akshare is not installed.\n"
                "[ECHOLON] `echolon init` needs it to download SHFE data.\n"
                "[ECHOLON]\n"
                "[ECHOLON] Install with:\n"
                "[ECHOLON]   pip install akshare\n",
                err=True,
            )
            raise typer.Exit(3)

        _full_init_shfe(
            instrument_data_root=instrument_data_root,
            instrument=instrument, instrument_code=instrument_code,
            start=start, end=end,
        )
    else:
        typer.echo(
            f"--market {market} not yet wired into `echolon init` (v1 covers SHFE only).\n"
            f"Want another market? See echolon's BaseExtractor and consider opening an issue.",
            err=True,
        )
        raise typer.Exit(2)

    # Scaffold strategy from template into workspace/strategy/baseline/.
    strategy_root = target / "strategy" / "baseline"
    strategy_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_path(template), strategy_root, dirs_exist_ok=True)
    typer.echo(f"[ECHOLON]   strategy/baseline/ ({template} template — fill in the logic)")

    # Workspace marker — records both ctx and the PathsConfig overrides so
    # `echolon backtest single` recovers the chosen consolidated layout.
    write_marker(
        target,
        market=market, instrument=instrument, instrument_code=instrument_code,
        frequency="interday", bar_size="1d",
        date_range=(start, end),
        data_source=("test_stub" if test_stub else "akshare"),
        initial_capital=initial_capital,
        paths={
            "market_data_dir": "data",
            "raw_data_dir": "data",
            "indicators_backtest_dir": "workspace/indicators",
        },
    )

    # Pre-create indicator slot dir + workspace/backtest so the subsequent
    # `backtest single` lands artifacts in the right place.
    indicators_root.mkdir(parents=True, exist_ok=True)
    (target / "workspace" / "backtest").mkdir(parents=True, exist_ok=True)

    # READMEs documenting the two trees.
    _write_data_readmes(target)

    # Drop a local copy of llms.txt at the workspace root. An LLM agent that
    # walks into this directory finds it without needing the MCP server up,
    # which short-circuits the "which CLI verb do I use?" wandering and makes
    # the operating loop self-evident from cwd alone.
    _copy_llms_txt(target)

    typer.echo("")
    typer.echo("[ECHOLON] Next:")
    typer.echo(f"[ECHOLON]   1. Open {target.name}/ in your MCP-aware editor.")
    typer.echo(f"[ECHOLON]   2. Fill in the logic in {target.name}/strategy/baseline/.")
    typer.echo(f"[ECHOLON]      Or ask the LLM agent to do it via echolon-mcp's tools.")
    typer.echo(f"[ECHOLON]   3. Run: echolon backtest {target.name}/strategy/baseline/")


def _full_init_shfe(*, instrument_data_root: Path, instrument: str, instrument_code: str,
                    start: str, end: str) -> None:
    """Real SHFE full-init: download via akshare, derive main_contract from
    per-contract volume series, write all artifacts under the consolidated
    layout ``{instrument_data_root}/`` (= ``data/{market}/{instrument}/``).
    """
    import pandas as pd

    typer.echo(f"[ECHOLON] Downloading {instrument_code} data via akshare...")
    from echolon.data.extractors.shfe.akshare_extractor import SHFEAkshareExtractor
    extractor = SHFEAkshareExtractor(market="SHFE", asset=instrument)
    raw_df = extractor.extract_raw(start_date=start, end_date=end, save=False)
    if raw_df.empty:
        typer.echo("No data returned by akshare for the requested range.", err=True)
        raise typer.Exit(3)

    instrument_data_root.mkdir(parents=True, exist_ok=True)
    contract_dir = instrument_data_root / "sort_by_contract"
    contract_dir.mkdir(exist_ok=True)
    for contract, group in raw_df.groupby("contract"):
        group.to_csv(contract_dir / f"{contract}.csv", index=False)
    raw_df.sort_values("date").to_csv(instrument_data_root / "sort_by_date.csv", index=False)
    pd.DataFrame({
        "date": sorted(raw_df["date"].unique()), "is_trading_day": True,
    }).to_csv(instrument_data_root / "trading_calendar.csv", index=False)

    typer.echo("[ECHOLON]   Building main_contract.csv (max-volume rule)")
    _derive_main_contract_from_volume(
        raw_df, instrument_data_root / "main_contract.csv",
    )
    typer.echo(
        f"[ECHOLON]   data/SHFE/{instrument}/ "
        f"({len(raw_df['contract'].unique())} contracts, {len(raw_df)} rows)"
    )


def _derive_main_contract_from_volume(raw_df, out_path: Path) -> None:
    """Pick the contract with maximum daily volume per trading date.

    Output schema: ``date,main_contract``.
    """
    import pandas as pd
    df = raw_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    idx = df.groupby("date")["volume"].idxmax()
    out = df.loc[idx, ["date", "contract"]].rename(columns={"contract": "main_contract"})
    out["main_contract"] = out["main_contract"].apply(
        lambda c: c if str(c).lower().endswith(".sf") else f"{c}.SF"
    )
    out.sort_values("date").to_csv(out_path, index=False)


def _copy_llms_txt(target: Path) -> None:
    """Copy the package-shipped llms.txt to the workspace root so an LLM
    agent walking into the project finds the operating loop without needing
    the MCP server up.
    """
    from importlib.resources import files
    src_text = files("echolon").joinpath("llms.txt").read_text(encoding="utf-8")
    (target / "llms.txt").write_text(src_text, encoding="utf-8")


def _write_data_readmes(target: Path) -> None:
    """Write minimal READMEs for the data/ and workspace/ trees."""
    (target / "data" / "README.md").write_text(
        "# Source Data\n\n"
        "Per-(market, instrument) data fetched by `echolon init` (akshare for "
        "SHFE) or supplied manually. Layout:\n\n"
        "```\n"
        "data/\n"
        "  SHFE/\n"
        "    aluminum/\n"
        "      main_contract.csv         # max-volume rule\n"
        "      sort_by_date.csv\n"
        "      sort_by_contract/\n"
        "        al2401.csv\n"
        "        ...\n"
        "      trading_calendar.csv\n"
        "```\n\n"
        "Edit/replace any file to override the akshare-derived defaults.\n"
    )
    (target / "workspace" / "README.md").write_text(
        "# Working Artifacts (Regenerable)\n\n"
        "Computed indicators + backtest results. Safe to delete and "
        "re-derive from `data/`. Layout:\n\n"
        "```\n"
        "workspace/\n"
        "  indicators/\n"
        "    baseline/                   # one slot per strategy variant\n"
        "      strategy_indicators.csv\n"
        "      strategy_indicator_metadata.json\n"
        "      by_contract/\n"
        "  backtest/                     # latest run's results + logs\n"
        "```\n"
    )


def _write_stub_data(instrument_data_root: Path, instrument: str, instrument_code: str) -> None:
    """Test-stub: skip akshare, write a few rows of synthetic data into the
    consolidated layout.
    """
    import pandas as pd
    (instrument_data_root / "sort_by_contract").mkdir(parents=True, exist_ok=True)
    stub = pd.DataFrame({
        "contract": ["al2401"] * 3,
        "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "prev_close": [19000.0, 19030.0, 19060.0],
        "prev_settlement": [19000.0, 19030.0, 19060.0],
        "open": [19000.0, 19030.0, 19060.0],
        "high": [19050.0, 19080.0, 19110.0],
        "low":  [18990.0, 19000.0, 19020.0],
        "close": [19030.0, 19060.0, 19090.0],
        "settlement": [19030.0, 19060.0, 19090.0],
        "price_change": [0.0, 30.0, 30.0],
        "settlement_change": [0.0, 30.0, 30.0],
        "volume": [5000.0, 6000.0, 5500.0],
        "turnover": [95.15, 114.36, 105.0],
        "open_interest": [30000.0, 31000.0, 30500.0],
    })
    stub.to_csv(instrument_data_root / "sort_by_contract" / "al2401.csv", index=False)
    stub.to_csv(instrument_data_root / "sort_by_date.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02"], "is_trading_day": True}).to_csv(
        instrument_data_root / "trading_calendar.csv", index=False
    )
    pd.DataFrame({
        "date": ["2024-01-02"], "main_contract": ["al2401.SF"],
    }).to_csv(instrument_data_root / "main_contract.csv", index=False)
