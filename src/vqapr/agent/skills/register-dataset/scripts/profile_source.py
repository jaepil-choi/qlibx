"""Report what a source file PROVES about itself, and nothing it merely suggests.

    python profile_source.py PATH [--json]

PRD §11.1 splits a registration proposal in two, and the halves are confirmed differently:

    the data proves it        a key that is not unique, four numbers with a fixed ordering,
                              a column with six distinct values, a timestamp with no zone
                              -> the agent may settle these

    the name is all we know   which of the four is the opening price, whether that date is
                              the observation or the publication, whether that boolean means
                              halted -> the USER must settle these

This script fills the first column only. It never guesses which column is a close, what a date
means, or what a flag encodes, because none of that is falsifiable from the values: swap the open
and the close and both still sit between the high and the low.

Reads csv, tsv, parquet and hive-partitioned directories through duckdb, which vqapr already
depends on. Spreadsheets are refused with the reason rather than half-read.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import duckdb

MAX_KEY_WIDTH = 3
"""How many columns a key candidate may combine.

Wider than three is a combinatorial search, and a logical key that needs four columns is a
question for the user rather than an answer to find here.
"""

LOW_CARDINALITY = 50
"""Distinct values at or below which a column reads as a label rather than a measurement.

PRD §4.1's "낮은 카디널리티 문자열과 값의 쌍 -> field별 저장": a long table keyed by such a column
is usually one field per value, not one field carrying names.
"""

SAMPLE_ROWS = 5


def _relation(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"} or path.is_dir():
        target = f"{path.as_posix()}/**/*.parquet" if path.is_dir() else path.as_posix()
        return f"read_parquet('{target}', hive_partitioning=true, union_by_name=true)"
    if suffix in {".csv", ".tsv", ".txt"}:
        return f"read_csv_auto('{path.as_posix()}', sample_size=-1)"
    raise SystemExit(
        f"cannot read {path.name}: this profiler reads csv, tsv, parquet and parquet "
        "directories. A spreadsheet holds formatting and merged cells that change what a "
        "column means, so convert it deliberately (pandas.read_excel then to_parquet) and "
        "profile the result -- that conversion is a decision, not a detail to hide here."
    )


def _columns(con: duckdb.DuckDBPyConnection, rel: str) -> list[tuple[str, str]]:
    return [(row[0], row[1]) for row in con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()]


def _quote(name: str) -> str:
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def _one_row(cursor: duckdb.DuckDBPyConnection) -> tuple[Any, ...]:
    """The row an aggregate query always yields; none is duckdb breaking its contract."""
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("an aggregate query returned no row")
    return row


def _column_facts(
    con: duckdb.DuckDBPyConnection, rel: str, columns: list[tuple[str, str]], rows: int
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for name, dtype in columns:
        col = _quote(name)
        distinct, nulls, low, high = _one_row(
            con.execute(
                f"SELECT count(DISTINCT {col}), count(*) - count({col}), "
                f"min({col})::VARCHAR, max({col})::VARCHAR FROM {rel}"
            )
        )
        entry: dict[str, Any] = {
            "type": dtype,
            "distinct": distinct,
            "nulls": nulls,
            "null_share": round(nulls / rows, 6) if rows else None,
            "min": low,
            "max": high,
        }
        if 0 < distinct <= LOW_CARDINALITY:
            entry["values"] = [
                row[0]
                for row in con.execute(
                    f"SELECT DISTINCT {col} FROM {rel} WHERE {col} IS NOT NULL "
                    f"ORDER BY 1 LIMIT {LOW_CARDINALITY}"
                ).fetchall()
            ]
        facts[name] = entry
    return facts


def _timestamp_facts(
    con: duckdb.DuckDBPyConnection, rel: str, columns: list[tuple[str, str]]
) -> dict[str, Any]:
    """Zone-awareness and the wall clocks a timestamp column actually lands on.

    A column whose every value is midnight is a DATE that someone widened, not an observation
    instant -- and the difference is exactly where a look-ahead hides. The script reports the
    clocks; what instant is defensible is the user's to say.
    """
    facts: dict[str, Any] = {}
    for name, dtype in columns:
        upper = dtype.upper()
        if "TIMESTAMP" not in upper and "DATE" not in upper:
            continue
        col = _quote(name)
        aware = "WITH TIME ZONE" in upper or upper.endswith("TZ")
        entry: dict[str, Any] = {"type": dtype, "timezone_aware": aware}
        if "DATE" not in upper or "TIMESTAMP" in upper:
            entry["wall_clocks"] = [
                row[0]
                for row in con.execute(
                    f"SELECT DISTINCT strftime({col}, '%H:%M:%S') AS t FROM {rel} "
                    f"WHERE {col} IS NOT NULL ORDER BY 1 LIMIT 12"
                ).fetchall()
            ]
        facts[name] = entry
    return facts


def _key_candidates(
    con: duckdb.DuckDBPyConnection, rel: str, columns: list[tuple[str, str]], rows: int
) -> list[dict[str, Any]]:
    """Column combinations that are unique over every row, narrowest first.

    A combination that is NOT unique is the finding worth acting on: it means the table carries
    more than one row per (name, instant) and needs another key axis, or is a `rows` grain.

    Floating-point columns are excluded. On the shipped sample panel, `open`, `high` and `low`
    were each unique across 6,900 rows -- true, and meaningless: continuous measurements collide
    rarely, so uniqueness there is an accident of the values rather than a property of the table.
    Reported as a key candidate it invites `key_fields: [open]`, which registers and then loses a
    row the day two names open at the same price. Integers stay, because an integer column is as
    likely to be an identifier as a measurement and the data cannot tell which.
    """
    names = [
        name
        for name, dtype in columns
        if not any(token in dtype.upper() for token in ("DOUBLE", "FLOAT", "REAL", "DECIMAL"))
    ]
    found: list[dict[str, Any]] = []
    for width in range(1, MAX_KEY_WIDTH + 1):
        for combo in combinations(names, width):
            if any(set(hit["fields"]) <= set(combo) for hit in found):
                continue  # a superset of a key is trivially a key
            cols = ", ".join(_quote(name) for name in combo)
            distinct = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {cols} FROM {rel})")
            unique = _one_row(distinct)[0]
            if unique == rows:
                found.append({"fields": list(combo), "unique": True})
    return found


def _orderings(
    con: duckdb.DuckDBPyConnection, rel: str, columns: list[tuple[str, str]]
) -> list[str]:
    """Inequalities that hold on every row of a numeric pair.

    Four numbers where two bound the other two is the shape of a price bar, and that much the
    data does prove. Which of the inner two is the OPEN it does not -- that asymmetry is the
    whole reason this script reports the relation and stops.
    """
    numeric = [
        name
        for name, dtype in columns
        if any(token in dtype.upper() for token in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL"))
    ]
    held: list[str] = []
    for left, right in combinations(numeric, 2):
        a, b = _quote(left), _quote(right)
        violations = _one_row(
            con.execute(
                f"SELECT count(*) FROM {rel} "
                f"WHERE {a} IS NOT NULL AND {b} IS NOT NULL AND {a} > {b}"
            )
        )[0]
        if violations == 0:
            held.append(f"{left} <= {right}")
            continue
        violations = _one_row(
            con.execute(
                f"SELECT count(*) FROM {rel} "
                f"WHERE {a} IS NOT NULL AND {b} IS NOT NULL AND {b} > {a}"
            )
        )[0]
        if violations == 0:
            held.append(f"{right} <= {left}")
    return held


def _coverage(
    con: duckdb.DuckDBPyConnection, rel: str, group: str, instant: str
) -> dict[str, Any]:
    """First and last observation per name -- the evidence behind a listing or a delisting."""
    g, t = _quote(group), _quote(instant)
    rows = con.execute(
        f"SELECT {g}, min({t})::VARCHAR, max({t})::VARCHAR, count(*) FROM {rel} "
        f"GROUP BY 1 ORDER BY 2, 1"
    ).fetchall()
    spans = [
        {"value": row[0], "first": row[1], "last": row[2], "rows": row[3]} for row in rows
    ]
    first_seen = {span["first"] for span in spans}
    last_seen = {span["last"] for span in spans}
    return {
        "group": group,
        "instant": instant,
        "members": len(spans),
        "balanced": len(first_seen) == 1 and len(last_seen) == 1,
        "sample": spans[:SAMPLE_ROWS],
        "late_starters": [s for s in spans if s["first"] != min(first_seen)][:SAMPLE_ROWS],
        "early_enders": [s for s in spans if s["last"] != max(last_seen)][:SAMPLE_ROWS],
    }


def profile(path: Path) -> dict[str, Any]:
    rel = _relation(path)
    con = duckdb.connect()
    columns = _columns(con, rel)
    rows = _one_row(con.execute(f"SELECT count(*) FROM {rel}"))[0]
    if rows == 0:
        raise SystemExit(f"{path} holds no rows; there is nothing to register")

    timestamps = _timestamp_facts(con, rel, columns)
    report: dict[str, Any] = {
        "path": str(path),
        "rows": rows,
        "columns": _column_facts(con, rel, columns, rows),
        "timestamps": timestamps,
        "unique_keys": _key_candidates(con, rel, columns, rows),
        "orderings_that_always_hold": _orderings(con, rel, columns),
    }

    # Coverage needs a name axis and an instant axis. Both are guesses about ROLE, so the pairing
    # is offered as a candidate and labelled as one rather than reported as a fact.
    labels = [
        name
        for name, facts in report["columns"].items()
        if name not in timestamps and 1 < facts["distinct"] <= max(LOW_CARDINALITY, rows // 2)
    ]
    if labels and timestamps:
        report["coverage_if"] = _coverage(con, rel, labels[0], next(iter(timestamps)))

    return report


def _render(report: dict[str, Any]) -> str:
    lines = [
        f"{report['path']}  --  {report['rows']:,} rows",
        "",
        "PROVEN BY THE DATA (settle these yourself)",
    ]
    for key in report["unique_keys"][:3]:
        lines.append(f"  unique on: {', '.join(key['fields'])}")
    if not report["unique_keys"]:
        lines.append(
            f"  NO combination of up to {MAX_KEY_WIDTH} columns is unique -- this table carries "
            "several rows per key. It is a `rows` grain, or it needs another key axis."
        )
    for held in report["orderings_that_always_hold"]:
        lines.append(f"  always: {held}")
    for name, facts in report["timestamps"].items():
        aware = "timezone-aware" if facts["timezone_aware"] else "NAIVE -- registration refuses it"
        clocks = facts.get("wall_clocks")
        clock_note = f", wall clocks {clocks}" if clocks else ""
        lines.append(f"  {name}: {facts['type']}, {aware}{clock_note}")
    for name, facts in report["columns"].items():
        if "values" in facts:
            lines.append(f"  {name}: {facts['distinct']} distinct -- {facts['values'][:8]}")
        if facts["nulls"]:
            lines.append(f"  {name}: {facts['nulls']:,} nulls ({facts['null_share']:.1%})")
    coverage = report.get("coverage_if")
    if coverage:
        shape = "balanced" if coverage["balanced"] else "UNBALANCED"
        lines += [
            "",
            f"IF {coverage['group']} is the name axis and {coverage['instant']} the instant:",
            f"  {coverage['members']} members, {shape}",
        ]
        for span in coverage["late_starters"]:
            lines.append(f"  starts late: {span['value']} first seen {span['first']}")
        for span in coverage["early_enders"]:
            lines.append(f"  ends early:  {span['value']} last seen {span['last']}")

    # Only the questions this file actually raises. A fixed list would have the agent asking
    # about an opening price in a table that holds no ordered numbers, and a reader learns to
    # skim a section that is the same every time -- which is the one section that must be read.
    asks: list[str] = []
    if report["orderings_that_always_hold"]:
        asks.append(
            "  which of the ordered numbers is the OPEN and which the CLOSE -- the ordering "
            "above holds whichever way you assign them, so the data cannot answer this"
        )
    for name, facts in report["timestamps"].items():
        asks.append(
            f"  is {name} the observation, the publication, or a revision? "
            + (
                f"every value lands at {facts['wall_clocks'][0]}, so if that is a stamped "
                "date rather than an observed instant, what instant is defensible?"
                if len(facts.get("wall_clocks") or []) == 1
                else "and in which timezone is it stated?"
            )
        )
    for name, facts in report["columns"].items():
        if "values" in facts and facts["distinct"] <= 8:
            asks.append(f"  what does each value of {name} MEAN? {facts['values']}")
    if coverage and not coverage["balanced"]:
        asks.append(
            f"  a name missing from {coverage['instant']} -- is it not listed, or listed and "
            "not traded that day? The two are different exclusions and only you know which"
        )
    if asks:
        lines += ["", "NOT PROVEN -- ASK THE USER (do not answer these from column names)", *asks]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report what a source file proves about itself: unique keys, orderings that always "
            "hold, timezone awareness, label cardinality, per-name coverage."
        )
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    if not args.path.exists():
        raise SystemExit(f"no such path: {args.path}")

    report = profile(args.path)
    text = json.dumps(report, indent=2, default=str) if args.json else _render(report)
    _write(text)
    return 0


def _write(text: str) -> None:
    """Write as UTF-8 bytes rather than through the inherited console encoding.

    This profiler exists to show the user their own values, and those values are the reason:
    a cp949 console turned the sample's Korean instrument names into mojibake, which is both
    unreadable and, in an interview about what a label means, actively misleading.
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)
        return
    stream.write(text.encode("utf-8") + b"\n")
    stream.flush()


if __name__ == "__main__":
    sys.exit(main())
