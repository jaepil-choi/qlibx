"""`vqapr export <run-id>/<strategy-id>@<fp8> --out <dir>` -- one strategy record as files.

Record `266`. The incremental testbed's three vqapr agents each had to hand a result over as plain
files -- a daily NAV and a log -- and each wrote an exporter of its own that failed on the way:
tuple keys in `json.dumps`, `Decimal += str`, `str < int`, a NAV of NaN from taking the last row
of the day over every account row rather than the `_ACCOUNT` rows. The logic they rewrote was
already in the package, inside the report.

So this writes what the record and the report already hold, through the readers they already
use, and computes nothing new:

- `nav.csv` and `holdings.csv` from `valuation_grid` -- the series `strategy_report` measures, so
  `nav.csv` IS `performance.nav`, the opening point included;
- `fills.csv`, `weights.csv` and, when the run declared a rule, `monitoring.csv`: the package's
  tables as recorded;
- `tables/<table>.csv` for each table the strategy formed (a subdirectory, so no author's table
  name can collide with the package's files);
- `report.json`: `strategy_report(...).as_record()`.

A number is written as exact decimal text without an exponent, never through a float; an instant is
ISO 8601 with the offset it was recorded in, and `date` beside it is the local date of that
instant. Nothing is joined: a strategy's own log against the fill prices is the author's question,
asked of `fills.csv`.

It does not write parquet: the store already is parquet (`reading-a-record.md`).
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.show import resolve_strategy
from vqapr.domain.errors import VALUE_INVALID, InputError
from vqapr.project.store import WORKSPACE_DIRECTORY
from vqapr.record import read_table, table_ids
from vqapr.report.record import (
    ACCOUNT_TABLE,
    FILL_TABLE,
    MONITORING_TABLE,
    WEIGHT_TABLE,
    strategy_report,
    valuation_grid,
)

NAV_FILE = "nav.csv"
HOLDINGS_FILE = "holdings.csv"
REPORT_FILE = "report.json"
TABLES_DIRECTORY = "tables"
PACKAGE_TABLE_FILES = {
    FILL_TABLE: "fills.csv",
    WEIGHT_TABLE: "weights.csv",
    MONITORING_TABLE: "monitoring.csv",
}
"""The package's tables and the file each becomes. `vqapr.account` is not among them: its rows are
the grid, written as `nav.csv` (one row per valuation) and `holdings.csv` (one per name held)."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "identifier",
        help=(
            "`<run-id>/<strategy-id>@<fp8>`, or `<run-id>/<strategy-id>` when one record of it "
            "exists -- the form `vqapr show strategy` takes"
        ),
    )
    parser.add_argument(
        "--out",
        dest="out",
        type=Path,
        required=True,
        help="directory to write the files into (created when missing)",
    )
    parser.add_argument(
        "--store-root",
        dest="store_root",
        type=Path,
        default=None,
        help="where run records live, when they were written outside the workspace directory",
    )
    parser.add_argument(
        "--force",
        dest="force",
        action="store_true",
        help="replace files an earlier export left in --out, instead of refusing",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    root = args.store_root or project_root / WORKSPACE_DIRECTORY
    run_id, strategy_ref = resolve_strategy(root, args.identifier)
    out: Path = args.out
    authored = [
        table
        for table in table_ids(root, run_id, strategy_ref)
        if table != ACCOUNT_TABLE and table not in PACKAGE_TABLE_FILES
    ]
    present = set(table_ids(root, run_id, strategy_ref))
    planned: dict[str, Path] = {
        NAV_FILE: out / NAV_FILE,
        HOLDINGS_FILE: out / HOLDINGS_FILE,
        **{
            table: out / name
            for table, name in PACKAGE_TABLE_FILES.items()
            if table in present
        },
        **{table: out / TABLES_DIRECTORY / f"{table}.csv" for table in authored},
        REPORT_FILE: out / REPORT_FILE,
    }
    existing = [path for path in planned.values() if path.exists()]
    if existing and not args.force:
        raise InputError(
            VALUE_INVALID,
            requirement="export writes into a directory that does not already hold its files",
            observed=", ".join(str(path) for path in existing),
            retry=f"pass --force to replace them, or choose another --out than {out}",
        )

    written: list[dict[str, Any]] = []
    grid = valuation_grid(root, run_id, strategy_ref)
    written.append(
        _write(
            planned[NAV_FILE],
            ("event_time", "date", "account_version", "cash", "nav"),
            (
                {
                    "event_time": point.at,
                    "date": point.at.date(),
                    "account_version": point.version,
                    "cash": point.cash,
                    "nav": point.nav,
                }
                for point in grid
            ),
        )
    )
    written.append(
        _write(
            planned[HOLDINGS_FILE],
            ("event_time", "date", "instrument", "quantity", "price", "value"),
            (
                {
                    "event_time": point.at,
                    "date": point.at.date(),
                    "instrument": name,
                    "quantity": held.quantity,
                    "price": held.price,
                    "value": None if held.price is None else held.quantity * held.price,
                }
                for point in grid
                for name, held in sorted(point.positions.items())
            ),
        )
    )
    for table in (*PACKAGE_TABLE_FILES, *authored):
        if table not in planned:
            continue
        rows = list(read_table(root, run_id, table, strategy_ref))
        written.append(_write(planned[table], _columns(rows), rows))

    omitted: dict[str, str] = {}
    try:
        report = strategy_report(root, run_id, strategy_ref).as_record()
    except ValueError as unreportable:
        omitted[REPORT_FILE] = str(unreportable)
    else:
        planned[REPORT_FILE].parent.mkdir(parents=True, exist_ok=True)
        planned[REPORT_FILE].write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append({"path": str(planned[REPORT_FILE]), "rows": None})
    return success(
        "strategy.export",
        run_id=run_id,
        strategy_ref=strategy_ref,
        out=str(out),
        files=written,
        omitted=omitted,
    )


def _columns(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    """Every column the rows carry, `event_time` and its `date` first, then in first-seen order."""
    seen: dict[str, None] = {}
    for row in rows:
        seen.update(dict.fromkeys(row))
    if "event_time" in seen:
        return ("event_time", "date", *(column for column in seen if column != "event_time"))
    return tuple(seen)


def _write(
    path: Path, columns: tuple[str, ...], rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            cells = dict(row)
            if "date" in columns and "date" not in cells:
                instant = cells.get("event_time")
                cells["date"] = instant.date() if isinstance(instant, datetime) else None
            writer.writerow([_cell(cells.get(column)) for column in columns])
            count += 1
    return {"path": str(path), "rows": count}


def _cell(value: object) -> str:
    """One value as CSV text: exact decimals without an exponent, instants with their offset."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
