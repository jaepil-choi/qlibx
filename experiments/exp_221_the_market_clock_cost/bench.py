"""The cost of one market-clock instant, per instrument -- the measurement the one-loop campaign
(`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) gates its performance work on.

Builds a project of NAMES instruments with a daily observation table and a MINUTE execution
table over DAYS trading days (390 instants a day), a strategy that rebalances equal-weight every
EVERY, and the shipped `no-short` rule; then profiles `run()` alone. Everything the loop does at a
market-clock instant -- the snapshot, the mark, the `vqapr.account` rows, the compliance
observation -- is exercised NAMES times per instant, which is the axis the owner cares about
(3,000 names). The build and preflight are timed but not profiled.

    uv run python experiments/exp_221_the_market_clock_cost/bench.py --names 3000 --days 1
    uv run python experiments/exp_221_the_market_clock_cost/bench.py --names 300 --days 3 --no-positions

Prints the run's own `timing` (what the record reports), the top of the profile, and how many
mark objects the finished result still holds -- the memory axis.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import io
import json
import pstats
import shutil
import time
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

import duckdb

from vqapr.cli.main import main
from vqapr.domain.instruments import export_roster
from vqapr.public import Workspace, preflight_run, register_compliance, run, shipped_compliance_path

DATES = (
    "2024-03-04", "2024-03-05", "2024-03-06", "2024-03-07", "2024-03-08",
    "2024-03-11", "2024-03-12", "2024-03-13", "2024-03-14", "2024-03-15",
    "2024-03-18", "2024-03-19", "2024-03-20", "2024-03-21", "2024-03-22",
    "2024-03-25", "2024-03-26", "2024-03-27", "2024-03-28", "2024-03-29",
)
RETAINED = ("Mark", "MarkBatch", "SelectedMark", "AccountMark", "ValuationEvidence", "LifecycleTrace")


def _cli(*argv: str) -> dict:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    assert code == 0, payload
    return payload


def build(root: Path, names: int, dates: tuple[str, ...], every: str) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    instruments = [f"I{i:05d}" for i in range(names)]
    observation = (root / "observation.parquet").as_posix()
    execution = (root / "execution.parquet").as_posix()
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Seoul'")
    con.execute(
        f"CREATE TABLE names AS SELECT 'I' || lpad(i::VARCHAR, 5, '0') AS instrument, i "
        f"FROM range({names}) t(i)"
    )
    dates_sql = ", ".join(f"DATE '{d}'" for d in dates)
    con.execute(f"CREATE TABLE days AS SELECT unnest([{dates_sql}]) AS session_date")
    con.execute("CREATE TABLE minutes AS SELECT m FROM range(390) t(m)")
    con.execute(
        "COPY (SELECT (session_date::TIMESTAMP + INTERVAL 3 HOUR)::TIMESTAMPTZ AS available_at, "
        "session_date, instrument, (100.0 + (i % 50))::DOUBLE AS close FROM days, names) "
        f"TO '{observation}' (FORMAT PARQUET)"
    )
    con.execute(
        "COPY (SELECT (session_date::TIMESTAMP + INTERVAL 9 HOUR + to_minutes(m::BIGINT))::TIMESTAMPTZ "
        "AS trade_at, instrument, true AS is_tradable, (100.0 + (i % 50) + m * 0.01)::DOUBLE AS close "
        "FROM days, names, minutes ORDER BY trade_at, instrument) "
        f"TO '{execution}' (FORMAT PARQUET)"
    )
    con.close()
    (root / "venue.py").write_text(
        "from decimal import Decimal\n"
        "from vqapr.exchange.venue import AcademicExchange, TradeRule\n"
        "from vqapr.exchange.listings import ListingAccess\n"
        f"NAMES = [f'I{{i:05d}}' for i in range({names})]\n"
        "class Venue(AcademicExchange):\n"
        "    def __init__(self):\n"
        "        super().__init__({n: TradeRule(n, Decimal('1'), Decimal('1'), False, "
        "ListingAccess.LONG_ONLY) for n in NAMES})\n",
        encoding="utf-8",
    )
    (root / "strategy.py").write_text(
        "from vqapr import authoring as va\n"
        f"NAMES = [f'I{{i:05d}}' for i in range({names})]\n"
        "class EqualWeight(va.StrategyModel):\n"
        "    def inputs(self):\n"
        "        return {'prices': va.DatasetInput(dataset_id='prices', fields=('close',), "
        "lookback=va.RowsLookback(rows=1))}\n"
        "    def decide(self, call):\n"
        "        return va.Rebalance.of(long={n: 1 for n in NAMES}, invested='1.0')\n",
        encoding="utf-8",
    )
    (root / "workspace.yaml").write_text(
        "datasets:\n"
        "  prices:\n"
        "    source_id: price-source\n"
        f"    path: {observation}\n"
        "    instrument_field: instrument\n"
        "    available_at: available_at\n"
        "    grain: instrument_instant\n"
        "    key_fields: [available_at, instrument]\n"
        "    fields: {close: close}\n"
        "    field_types: {close: DOUBLE}\n"
        "  venue-minute:\n"
        "    source_id: venue-source\n"
        f"    path: {execution}\n"
        "    instrument_field: instrument\n"
        "    available_at: trade_at\n"
        "    grain: instrument_instant\n"
        "    key_fields: [trade_at, instrument]\n"
        "    fields: {close: close, is_tradable: is_tradable}\n"
        "    field_types: {close: DOUBLE, is_tradable: BOOLEAN}\n"
        "    execution: {is_tradable: is_tradable}\n"
        "components:\n"
        "  venue:\n"
        "    kind: exchange\n"
        f"    path: {(root / 'venue.py').as_posix()}\n"
        "    object_name: Venue\n"
        "  equal-weight:\n"
        "    kind: strategy\n"
        f"    path: {(root / 'strategy.py').as_posix()}\n"
        "    object_name: EqualWeight\n",
        encoding="utf-8",
    )
    _cli("--project-root", str(root), "register", str(root / "workspace.yaml"))
    written = export_roster({n: "stock" for n in instruments}, root / "roster")
    (root / "roster.yaml").write_text(
        "instruments:\n  tables:\n"
        + "".join(
            f"    {kind}: {path.relative_to(root).as_posix()}\n"
            for kind, path in sorted(written.items())
        ),
        encoding="utf-8",
    )
    _cli("--project-root", str(root), "register", str(root / "roster.yaml"))
    register_compliance(
        root,
        "no-short",
        shipped_compliance_path("no_short"),
        "NoShort",
        config={"compliance_id": "no-short"},
    )
    (root / "runs.yaml").write_text(
        json.dumps(
            {
                "runs": {
                    "bench": {
                        "writes": "bench-weights",
                        "strategy": {"component": "equal-weight"},
                        "timezone": "Asia/Seoul",
                        "agenda": {"every": every, "from": "09:00", "to": "15:29"},
                        "exchange": "venue",
                        "execution": {"dataset": "venue-minute", "trade_price": "close"},
                        "compliance": ["no-short"],
                        "start": f"{dates[0]}T00:00:00+09:00",
                        "end": f"{dates[-1]}T23:00:00+09:00",
                        "initial_account": {"cash": "100000000", "mode": "long_only"},
                        "instruments": instruments,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _cli("--project-root", str(root), "register", str(root / "runs.yaml"))


def measure(root: Path, names: int, days: int, every: str, positions: bool, top: int) -> None:
    dates = DATES[:days]
    started = time.perf_counter()
    build(root, names, dates, every)
    built = time.perf_counter()
    workspace = Workspace.open(root)
    frozen = preflight_run(workspace, workspace.run_definition("bench"))
    preflighted = time.perf_counter()
    profile = cProfile.Profile()
    profile.enable()
    outcome = run(
        root,
        frozen,
        store_root=root / "store",
        workspace=workspace,
        record_account_positions=positions,
    )
    profile.disable()
    finished = time.perf_counter()
    result = outcome.result()
    kept = Counter(type(item).__name__ for item in gc.get_objects())
    print(f"CONFIG names={names} days={days} every={every} positions={positions}")
    print(
        f"build={built - started:.1f}s preflight={preflighted - built:.1f}s "
        f"run={finished - preflighted:.1f}s events={len(result.occurrences)}"
    )
    timing = sorted(result.timing.items(), key=lambda item: -item[1])
    print("timing:", json.dumps({phase: round(seconds, 2) for phase, seconds in timing}))
    print("retained:", {name: kept[name] for name in RETAINED})
    profile.dump_stats(str(root / "run.prof"))
    for key in ("cumulative", "tottime"):
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats(key).print_stats(top)
        print(f"\n=== top {top} by {key} ===")
        for line in stream.getvalue().splitlines():
            if "vqapr" in line or "site-packages" in line or "function calls" in line:
                marker = "src\\vqapr" if "src\\vqapr" in line else "src/vqapr"
                head, _, tail = line.partition(marker)
                print(head.rsplit(" ", 1)[0] + " " + tail if tail else line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--names", type=int, default=300)
    parser.add_argument("--days", type=int, default=1, choices=range(1, len(DATES) + 1))
    parser.add_argument("--every", default="30m")
    parser.add_argument("--no-positions", action="store_true", help="record_account_positions=False")
    parser.add_argument("--root", type=Path, default=None, help="project directory; default under data/")
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()
    root = (args.root or Path("data") / "exp_221" / f"n{args.names}d{args.days}").resolve()
    measure(root, args.names, args.days, args.every, not args.no_positions, args.top)
