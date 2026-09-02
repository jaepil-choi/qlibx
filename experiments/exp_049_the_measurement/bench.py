"""The measurement `docs/issues/049` exists for, taken on this tree and reproducible from it.

`049` measured one model twice -- the same annual-fundamentals reduction against a statement
warehouse registered long at the vendor's grain, and against the same facts pivoted wide -- and
found 806.61 s against 1.31 s with `compute` at 0.36 s on both sides. The harness that took it
lived in a consumer repo and is gone (record `136`), and the tree has since changed what the two
sides *are*: a registration declares its grain, a `rows` grain is read as observations every
evaluation, a panel grain is scanned once per run and sliced by arithmetic (record `137`), and a
field is an expression, so the pivot can be declared instead of prepared (record `123`).

So this takes the measurement in the shape the tree now has, on synthetic statement facts that
are generated here, deterministically, with the properties the reduction depends on (two scopes,
quarterly and annual rows, an ordered code fallback that is actually exercised, and a later dump
bundle that must win). Three registrations of two files, one reduction:

    rows   the long file,  grain: rows,                 InstantsLookback,  Python does steps 1-3
    expr   the long file,  grain: instrument_instant,   each item an aggregate expression
    wide   a pre-pivoted file, grain: instrument_instant  -- 049's own `wide`

The anti-join is read before the timing, both directions, all three pairs: a side that is faster
and different is a different model, not a faster one (campaign gate "cost").

    uv run python experiments/exp_049_the_measurement/bench.py --instruments 1600 --evaluations 4

Outputs go under `outputs/` beside this file (gitignored): the generated parquet, the workspace,
the three published datasets, `result.json` and `RESULT.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from vqapr.public import (
    DatasetRegistration,
    MaterializationSpec,
    SourceSpec,
    materialize,
    register_data_model,
    register_dataset,
)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp049_models as models  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
FIRST_FISCAL_YEAR = 2018
NOISE_CODES = 12
LONG_COLUMNS = (
    "available_at",
    "instrument",
    "dump_source_label",
    "dump_last_modified",
    "statement_scope",
    "settlement_type",
    "account_code",
    "fiscal_yyyymm",
    "fiscal_year",
    "numeric_value",
)


def _code_rows() -> str:
    rows = []
    for item in models.ITEMS:
        for rank, code in enumerate(models.ACCOUNT_CODES[item]):
            rows.append(f"('{code}', {rank}, '{item}')")
    for index in range(NOISE_CODES):
        rows.append(f"('9{index:05d}', 0, 'noise')")
    return ", ".join(rows)


def generate_long(target: Path, *, instruments: int, years: int) -> int:
    """The vendor's long table, with the properties the reduction must handle.

    * 20% of (name, item) pairs lack the primary code, so the ordered fallback decides them;
    * 10% of names lack `total_equity` and 5% `controlling_equity`, so the book-equity chain
      reaches its second and third step; a third lack `noncontrolling_interest`;
    * half the rows come in two dump bundles, the older one carrying a value off by one, so
      "the latest bundle wins" is a rule with consequences;
    * the fallback code's value differs from the primary's by seven, so a fallback that fires
      is visible in the output.

    Values are integers stored as DOUBLE, so the three sides see the same Decimal.
    """
    sql = f"""
    COPY (
      WITH inst AS (SELECT i, printf('A%06d', i) AS instrument FROM range({instruments}) t(i)),
           yrs  AS (SELECT y FROM range({FIRST_FISCAL_YEAR}, {FIRST_FISCAL_YEAR + years}) t(y)),
           per  AS (SELECT * FROM (VALUES (3,'Q'),(6,'Q'),(9,'Q'),(12,'Q'),(12,'D'))
                    t(m, settlement_type)),
           scope AS (SELECT * FROM (VALUES ('C'),('S')) t(statement_scope)),
           codes AS (SELECT * FROM (VALUES {_code_rows()}) t(account_code, rank, item)),
           bundle AS (SELECT * FROM (VALUES ('b1', 0),('b2', 1)) t(dump_source_label, b)),
           base AS (
             SELECT *,
                    (make_date(y, m, 1) + INTERVAL 4 MONTH - INTERVAL 1 DAY)::DATE AS avail_date,
                    1000000 + (hash(instrument || item) % 9000) * 1000 AS base_value
             FROM inst, yrs, per, scope, codes, bundle
             WHERE NOT (rank = 0 AND item <> 'noise' AND hash(instrument || item) % 5 = 0)
               AND NOT (item = 'total_equity' AND hash(instrument || 'te') % 10 = 0)
               AND NOT (item = 'controlling_equity' AND hash(instrument || 'ce') % 20 = 0)
               AND NOT (item = 'noncontrolling_interest' AND hash(instrument || 'nci') % 3 = 0)
               AND (b = 0 OR hash(instrument, y, m, settlement_type, statement_scope, account_code) % 2 = 0)
           )
      SELECT
        (strftime(avail_date, '%Y-%m-%d') || ' 15:30:00+09:00')::TIMESTAMPTZ AS available_at,
        instrument,
        dump_source_label,
        (strftime(avail_date + INTERVAL (b) DAY, '%Y-%m-%d') || ' 09:00:00+09:00')::TIMESTAMPTZ
          AS dump_last_modified,
        statement_scope,
        settlement_type,
        account_code,
        y * 100 + m AS fiscal_yyyymm,
        y AS fiscal_year,
        (base_value
          + (y - {FIRST_FISCAL_YEAR}) * (hash(instrument || item || 'g') % 50) * 1000
          + m * 100
          + rank * 7
          + CASE WHEN statement_scope = 'S' THEN 3 ELSE 0 END
          - (1 - b))::DOUBLE AS numeric_value
      FROM base
      ORDER BY available_at, instrument, dump_source_label, statement_scope, settlement_type,
               account_code
    ) TO '{target.as_posix()}' (FORMAT PARQUET)
    """
    con = duckdb.connect()
    try:
        con.execute(sql)
        return con.execute(f"SELECT count(*) FROM '{target.as_posix()}'").fetchone()[0]
    finally:
        con.close()


def expression_fields() -> dict[str, str]:
    return {
        "fiscal_yyyymm": models.FISCAL_EXPRESSION,
        **{item: models.item_expression(item) for item in models.ITEMS},
    }


def generate_wide(long: Path, target: Path) -> int:
    """`049`'s wide file: the long file pivoted by exactly the expressions `expr` declares."""
    projections = ", ".join(f"{expr} AS {name}" for name, expr in expression_fields().items())
    sql = f"""
    COPY (
      SELECT available_at, instrument, {projections}
      FROM '{long.as_posix()}'
      GROUP BY available_at, instrument
      HAVING {models.FISCAL_EXPRESSION} IS NOT NULL
      ORDER BY available_at, instrument
    ) TO '{target.as_posix()}' (FORMAT PARQUET)
    """
    con = duckdb.connect()
    try:
        con.execute(sql)
        return con.execute(f"SELECT count(*) FROM '{target.as_posix()}'").fetchone()[0]
    finally:
        con.close()


def _timed(action):
    started = time.perf_counter()
    result = action()
    return result, time.perf_counter() - started


def register_all(project: Path, long: Path, wide: Path) -> dict[str, float]:
    timings: dict[str, float] = {}
    long_source = SourceSpec.of("sf-long-source", long)
    wide_source = SourceSpec.of("sf-wide-source", wide)

    _, timings["rows"] = _timed(
        lambda: register_dataset(
            project,
            DatasetRegistration.of(
                "sf_rows",
                "sf-long-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="rows",
                key_fields=(
                    "available_at",
                    "instrument",
                    "dump_source_label",
                    "statement_scope",
                    "settlement_type",
                    "account_code",
                ),
                fields={
                    "statement_scope": "statement_scope",
                    "settlement_type": "settlement_type",
                    "account_code": "account_code",
                    "fiscal_yyyymm": "fiscal_yyyymm",
                    "dump_last_modified": "dump_last_modified",
                    "numeric_value": "numeric_value",
                },
            ),
            long_source,
        )
    )
    _, timings["expr"] = _timed(
        lambda: register_dataset(
            project,
            DatasetRegistration.of(
                "sf_expr",
                "sf-long-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("available_at", "instrument"),
                fields=expression_fields(),
            ),
            long_source,
        )
    )
    _, timings["wide"] = _timed(
        lambda: register_dataset(
            project,
            DatasetRegistration.of(
                "sf_wide",
                "sf-wide-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("available_at", "instrument"),
                fields={name: name for name in expression_fields()},
            ),
            wide_source,
        )
    )
    model_file = HERE / "exp049_models.py"
    register_data_model(project, "on-rows", model_file, "OnRows")
    register_data_model(project, "on-expr", model_file, "OnExpr")
    register_data_model(project, "on-wide", model_file, "OnWide")
    return timings


def evaluation_times(years: int, evaluations: int) -> tuple[datetime, ...]:
    """Late June of the last `evaluations` fiscal years, after the March statements arrive."""
    last = FIRST_FISCAL_YEAR + years  # statements for fiscal year Y arrive in March of Y+1
    return tuple(datetime(year, 6, 30, 16, tzinfo=KST) for year in range(last - evaluations + 1, last + 1))


def run_side(project: Path, label: str, times, instruments, timing_file: Path):
    os.environ["EXP049_TIMING_FILE"] = str(timing_file)
    result, wall = _timed(
        lambda: materialize(
            project,
            f"on-{label}",
            MaterializationSpec.of(f"af_{label}", value_fields=models.OUTPUT_FIELDS),
            evaluation_times=times,
            instruments=instruments,
        )
    )
    compute = read = reduce = 0.0
    emitted = 0
    with timing_file.open(encoding="utf-8") as stream:
        for line in stream:
            entry = json.loads(line)
            if entry["model"] == label:
                compute += entry["compute_s"]
                read += entry["read_s"]
                reduce += entry["reduce_s"]
                emitted += entry["rows"]
    return {
        "label": label,
        "wall_s": wall,
        "per_evaluation_s": wall / len(times),
        "compute_s": compute,
        "read_s": read,
        "reduce_s": reduce,
        "framework_s": wall - compute,
        "emitted": emitted,
        "output": result.output_path,
    }


def anti_join(con: duckdb.DuckDBPyConnection, left: Path, right: Path) -> tuple[int, int]:
    columns = ", ".join(("available_at", "instrument", *models.OUTPUT_FIELDS))
    a = f"SELECT {columns} FROM '{left.as_posix()}'"
    b = f"SELECT {columns} FROM '{right.as_posix()}'"
    only_left = con.execute(f"SELECT count(*) FROM (({a}) EXCEPT ({b}))").fetchone()[0]
    only_right = con.execute(f"SELECT count(*) FROM (({b}) EXCEPT ({a}))").fetchone()[0]
    return only_left, only_right


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--instruments", type=int, default=1600)
    parser.add_argument("--years", type=int, default=8, help="fiscal years of statements")
    parser.add_argument("--evaluations", type=int, default=4)
    parser.add_argument("--sides", default="rows,expr,wide", help="comma list, in run order")
    args = parser.parse_args()
    sides = tuple(args.sides.split(","))

    outputs = HERE / "outputs"
    if outputs.exists():
        shutil.rmtree(outputs)
    outputs.mkdir(parents=True)
    project = outputs / "project"
    long_path = outputs / "statement_facts.parquet"
    wide_path = outputs / "statement_facts_wide.parquet"
    timing_file = outputs / "compute_timings.jsonl"
    timing_file.touch()

    print(f"generating: {args.instruments} instruments x {args.years} fiscal years", flush=True)
    long_rows, generate_long_s = _timed(
        lambda: generate_long(long_path, instruments=args.instruments, years=args.years)
    )
    wide_rows, generate_wide_s = _timed(lambda: generate_wide(long_path, wide_path))
    print(
        f"  long {long_rows:,} rows / {long_path.stat().st_size / 1e6:.1f} MB "
        f"({generate_long_s:.1f}s); wide {wide_rows:,} rows / "
        f"{wide_path.stat().st_size / 1e6:.2f} MB ({generate_wide_s:.1f}s)",
        flush=True,
    )

    print("registering", flush=True)
    registration = register_all(project, long_path, wide_path)
    for label, seconds in registration.items():
        print(f"  {label:5} {seconds:8.2f}s", flush=True)

    times = evaluation_times(args.years, args.evaluations)
    instruments = tuple(f"A{i:06d}" for i in range(args.instruments))
    print(
        f"materializing {len(times)} evaluations "
        f"({times[0].date()} .. {times[-1].date()}) x {len(instruments)} instruments",
        flush=True,
    )
    results = []
    for label in sides:
        outcome = run_side(project, label, times, instruments, timing_file)
        results.append(outcome)
        print(
            f"  {label:5} wall {outcome['wall_s']:9.2f}s  per eval {outcome['per_evaluation_s']:8.2f}s"
            f"  read {outcome['read_s']:8.2f}s  reduce {outcome['reduce_s']:6.2f}s"
            f"  framework {outcome['framework_s']:7.2f}s  emitted {outcome['emitted']:,}",
            flush=True,
        )

    # The anti-join is read BEFORE the timing is reported: campaign gate "cost".
    con = duckdb.connect()
    agreement = {}
    try:
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                left, right = results[i], results[j]
                only_left, only_right = anti_join(con, left["output"], right["output"])
                agreement[f"{left['label']}~{right['label']}"] = {
                    f"only_{left['label']}": only_left,
                    f"only_{right['label']}": only_right,
                }
        published = {
            r["label"]: con.execute(f"SELECT count(*) FROM '{r['output'].as_posix()}'").fetchone()[0]
            for r in results
        }
    finally:
        con.close()
    identical = all(all(v == 0 for v in pair.values()) for pair in agreement.values())
    print("anti-join (must be zero both ways before a timing is read):", flush=True)
    for pair, counts in agreement.items():
        print(f"  {pair:12} {counts}", flush=True)
    if not identical:
        print("SIDES DISAGREE -- the timings above are of different models, not the same one")

    rows_side = next((r for r in results if r["label"] == "rows"), None)
    ratios = {}
    if rows_side is not None:
        for r in results:
            if r["label"] != "rows" and r["wall_s"] > 0:
                ratios[f"rows/{r['label']}"] = rows_side["wall_s"] / r["wall_s"]

    summary = {
        "taken_at": datetime.now(KST).isoformat(timespec="seconds"),
        "tree": _git_head(),
        "parameters": vars(args),
        "data": {
            "long_rows": long_rows,
            "long_mb": round(long_path.stat().st_size / 1e6, 2),
            "wide_rows": wide_rows,
            "wide_mb": round(wide_path.stat().st_size / 1e6, 3),
        },
        "registration_s": registration,
        "sides": [{k: (str(v) if isinstance(v, Path) else v) for k, v in r.items()} for r in results],
        "published_rows": published,
        "agreement": agreement,
        "identical": identical,
        "ratios": ratios,
    }
    (outputs / "result.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (outputs / "RESULT.md").write_text(_markdown(summary), encoding="utf-8")
    print(f"\n{outputs / 'RESULT.md'}")
    return 0 if identical else 1


def _git_head() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
            cwd=HERE,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - provenance only
        return "unknown"


def _markdown(summary: dict) -> str:
    p = summary["parameters"]
    d = summary["data"]
    lines = [
        f"# 049 measurement -- `{summary['tree']}`, {summary['taken_at']}",
        "",
        f"{p['instruments']:,} instruments x {p['evaluations']} evaluations; "
        f"long {d['long_rows']:,} rows / {d['long_mb']} MB, wide {d['wide_rows']:,} rows / "
        f"{d['wide_mb']} MB.",
        "",
        "| side | wall | per eval | read (in callback) | reduce | framework | emitted | registration |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in summary["sides"]:
        lines.append(
            f"| {r['label']} | {r['wall_s']:.2f}s | {r['per_evaluation_s']:.2f}s | "
            f"{r['read_s']:.2f}s | {r['reduce_s']:.2f}s | {r['framework_s']:.2f}s | "
            f"{r['emitted']:,} | {summary['registration_s'][r['label']]:.2f}s |"
        )
    lines += [
        "",
        "`read` is the time inside the callback spent in `rows(alias)` (a scan, on `rows`) or "
        "`read(alias, field)` (a slice of the run's panel); `reduce` is the model's own "
        "arithmetic; `framework` is wall minus the callback -- window assembly, the panel build "
        "on its first read, output validation and publication.",
    ]
    lines += ["", "Anti-join, both directions:", ""]
    for pair, counts in summary["agreement"].items():
        lines.append(f"- `{pair}`: {counts}")
    lines.append("")
    lines.append("**Identical.**" if summary["identical"] else "**DIFFERENT -- not comparable.**")
    if summary["ratios"]:
        lines += ["", "Ratios (wall): " + ", ".join(f"{k} = {v:.1f}x" for k, v in summary["ratios"].items())]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
