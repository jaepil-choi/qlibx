"""Extract a deterministic real-market fixture slice from ``data/DW`` into parquet.

The observation row and the execution row for one session share the venue close instant: the
closing print is knowable exactly when it prints. A callback earlier in a later session therefore
sees only strictly prior sessions, while an execution or valuation at the close sees that close.

The warehouse under ``data/DW`` is local, gitignored vendor data. This tool turns a small,
explicitly bounded slice of it into the two physical inputs vqapr registers: one observation
dataset and one exact execution input. Nothing here invents prices, calendars, or tradability.

Run it before any showcase or test that requires real inputs::

    uv run python scripts/extract_dw_fixture.py --out <dir>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import duckdb

WAREHOUSE = Path("data/DW")
PRICES = WAREHOUSE / "fng_stock_daily_prices.csv"
MEMBERS = WAREHOUSE / "fng_k200_members.csv"

TICKER = "종목약코드"
TRADE_DATE = "거래일자"
CLOSE = "종가"
VOLUME = "거래량"
HALT = "거래정지구분"
ADMIN = "관리감리구분"

MEMBER_DATE = "일자"
MEMBER_TICKER = "종목코드2"
MEMBER_NAME = "종목명국문"
MEMBER_WEIGHT = "지수내비중"

OBSERVATION_LOCAL_TIME = "15:30:00"
EXECUTION_LOCAL_TIME = "15:30:00"
VENUE_ZONE = "Asia/Seoul"


@dataclass(frozen=True, slots=True)
class FixtureSpec:
    """One reproducible warehouse slice."""

    asof: str
    start: str
    end: str
    universe_size: int

    def __post_init__(self) -> None:
        for name, value in (("asof", self.asof), ("start", self.start), ("end", self.end)):
            if len(value) != 8 or not value.isdigit():
                raise ValueError(f"{name} must be YYYYMMDD")
        if self.start > self.end:
            raise ValueError("start must not be after end")
        if self.universe_size < 2:
            raise ValueError("universe_size must select at least two instruments")


def _csv(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"warehouse input is missing: {path}")
    return f"read_csv('{path.as_posix()}', header = true, all_varchar = true)"


def _universe(con: duckdb.DuckDBPyConnection, spec: FixtureSpec) -> list[dict[str, object]]:
    """Take the largest index members as of the last membership date at or before ``asof``."""
    members = _csv(MEMBERS)
    asof = con.execute(
        f'SELECT max("{MEMBER_DATE}") FROM {members} WHERE "{MEMBER_DATE}" <= ?', [spec.asof]
    ).fetchone()[0]
    if asof is None:
        raise ValueError(f"no index membership exists at or before {spec.asof}")
    selected = con.execute(
        f"""
        SELECT "{MEMBER_TICKER}" AS ticker,
               trim("{MEMBER_NAME}") AS name,
               CAST("{MEMBER_WEIGHT}" AS DOUBLE) AS index_weight
        FROM {members}
        WHERE "{MEMBER_DATE}" = ?
        ORDER BY index_weight DESC, ticker
        LIMIT ?
        """,
        [asof, spec.universe_size],
    ).fetchall()
    if len(selected) < spec.universe_size:
        raise ValueError(f"membership on {asof} has fewer than {spec.universe_size} rows")
    return [
        {"ticker": ticker, "name": name, "index_weight": weight, "membership_date": asof}
        for ticker, name, weight in selected
    ]


def _literal(value: str) -> str:
    """Only alphanumeric warehouse identifiers reach SQL text."""
    if not value.isalnum():
        raise ValueError(f"unexpected warehouse identifier: {value!r}")
    return f"'{value}'"


def _slice(con: duckdb.DuckDBPyConnection, spec: FixtureSpec, tickers: list[str]) -> None:
    """Register one typed view of exactly the requested tickers and trading days."""
    prices = _csv(PRICES)
    universe = ", ".join(_literal(ticker) for ticker in tickers)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW dw_slice AS
        SELECT "{TICKER}" AS instrument,
               strptime("{TRADE_DATE}", '%Y%m%d') AS session_date,
               CAST("{CLOSE}" AS DECIMAL(18, 4)) AS close,
               CAST("{VOLUME}" AS BIGINT) AS volume,
               trim("{HALT}") AS halt_flag,
               trim("{ADMIN}") AS admin_flag
        FROM {prices}
        WHERE "{TICKER}" IN ({universe})
          AND "{TRADE_DATE}" BETWEEN {_literal(spec.start)} AND {_literal(spec.end)}
          AND "{CLOSE}" IS NOT NULL
        """
    )


def extract(spec: FixtureSpec, out_dir: Path) -> dict[str, object]:
    """Write the observation dataset, the execution input, and a provenance manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    observation_path = out_dir / "observation_price_daily.parquet"
    execution_path = out_dir / "execution_krx_daily.parquet"
    manifest_path = out_dir / "fixture.json"

    con = duckdb.connect()
    try:
        universe = _universe(con, spec)
        tickers = [str(row["ticker"]) for row in universe]
        _slice(con, spec, tickers)

        sessions = con.execute(
            "SELECT count(DISTINCT session_date), min(session_date), max(session_date)"
            " FROM dw_slice"
        ).fetchone()
        if sessions[0] == 0:
            raise ValueError("warehouse slice is empty for the requested window")

        con.execute(
            f"""
            COPY (
              SELECT (session_date + INTERVAL '{OBSERVATION_LOCAL_TIME}')
                       AT TIME ZONE '{VENUE_ZONE}' AS available_at,
                     instrument,
                     close,
                     volume
              FROM dw_slice
              ORDER BY available_at, instrument
            ) TO '{observation_path.as_posix()}' (FORMAT PARQUET)
            """
        )
        con.execute(
            f"""
            COPY (
              SELECT (session_date + INTERVAL '{EXECUTION_LOCAL_TIME}')
                       AT TIME ZONE '{VENUE_ZONE}' AS trade_at,
                     instrument,
                     (halt_flag = '0') AS is_tradable,
                     close
              FROM dw_slice
              ORDER BY trade_at, instrument
            ) TO '{execution_path.as_posix()}' (FORMAT PARQUET)
            """
        )

        halted = con.execute("SELECT count(*) FROM dw_slice WHERE halt_flag <> '0'").fetchone()[0]
        supervised = con.execute(
            "SELECT count(*) FROM dw_slice WHERE admin_flag <> '1'"
        ).fetchone()[0]
        rows = con.execute("SELECT count(*) FROM dw_slice").fetchone()[0]
    finally:
        con.close()

    manifest = {
        "source": "data/DW (local vendor warehouse; not redistributed)",
        "spec": {
            "asof": spec.asof,
            "start": spec.start,
            "end": spec.end,
            "universe_size": spec.universe_size,
        },
        "universe": universe,
        "rows": rows,
        "sessions": sessions[0],
        "first_session": str(sessions[1]),
        "last_session": str(sessions[2]),
        "halted_rows": halted,
        "supervised_rows": supervised,
        "observation_path": observation_path.name,
        "execution_path": execution_path.name,
        "observation_local_time": OBSERVATION_LOCAL_TIME,
        "execution_local_time": EXECUTION_LOCAL_TIME,
        "venue_zone": VENUE_ZONE,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asof", default="20260331")
    parser.add_argument("--start", default="20260401")
    parser.add_argument("--end", default="20260529")
    parser.add_argument("--universe-size", type=int, default=6)
    args = parser.parse_args()

    spec = FixtureSpec(
        asof=args.asof, start=args.start, end=args.end, universe_size=args.universe_size
    )
    manifest = extract(spec, args.out)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
