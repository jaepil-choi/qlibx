"""Build the sample panel from the local warehouse.

The panel is deliberately unbalanced. One name starts after the window opens and one stops before
it closes, because a balanced panel would let a Strategy look correct while silently assuming every
instrument exists on every session. Neither case is signalled to the Strategy: a late lister simply
has too little history to score, and a delisted name simply stops appearing.

Observation and execution are separate files with separate contracts (architecture §3.6). The
execution table keeps a final tradable session for the delisted name, which is what lets the
position be closed rather than stranded.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

PRICE_TYPE = pa.decimal128(18, 4)
"""Prices stay exact. The row normalizer preserves the source scalar type, so writing floats here
would hand the Strategy floats and make its arithmetic inexact."""

WAREHOUSE = Path("data/DW/fng_stock_daily_prices.csv")
INSTRUMENT_MASTER = Path("data/DW/DW_FNG_FGSC종목_20200101-20260430.csv")
"""Names of listed shares. Codes absent here are funds rather than companies."""
SEOUL = ZoneInfo("Asia/Seoul")
CLOSE_HOUR, CLOSE_MINUTE = 15, 30
"""Daily close. A close price is not knowable before the session ends, so it is the availability."""

WINDOW_START, WINDOW_END = "20220101", "20241231"
INSTRUMENT_COUNT = 10
LATE_SESSIONS = 200
"""Sessions removed from the front of the late lister."""
DEAD_SESSIONS = 250
"""Sessions removed from the back of the delisted name."""

WIND_DOWN_SESSIONS = 3
"""Tradable sessions kept after the last observation of the delisted name.

A position is closed on the session after the Strategy stops targeting the name, and that fill
still needs a price. Real delistings have a wind-down period for the same reason, so keeping a
short tradable tail is what the market actually does rather than a convenience for the engine.
"""

_COLUMNS = {
    "code": "종목약코드",
    "date": "거래일자",
    "open": "시가",
    "high": "고가",
    "low": "저가",
    "close": "종가",
    "volume": "거래량",
    "value": "거래대금",
    "halt": "거래정지구분",
    "adjust": "수정계수",
}


@dataclass(frozen=True, slots=True)
class SamplePanel:
    observations: Path
    execution: Path
    instruments: tuple[str, ...]
    late_listed: str
    delisted: str
    sessions: tuple[str, ...]


def _available_at(session: str) -> datetime:
    local = datetime(
        int(session[:4]),
        int(session[4:6]),
        int(session[6:8]),
        CLOSE_HOUR,
        CLOSE_MINUTE,
        tzinfo=SEOUL,
    )
    return local.astimezone(UTC)


def _companies(master: Path) -> dict[str, str]:
    """Map code to company name, which also excludes funds from the selection."""
    names: dict[str, str] = {}
    with master.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            names.setdefault(row["종목약코드"], row["종목명"].strip())
    return names


def _select(warehouse: Path, master: Path) -> tuple[list[str], list[str]]:
    """Choose liquid companies that traded every session without a halt."""
    sessions: Counter[str] = Counter()
    halts: Counter[str] = Counter()
    traded: Counter[str] = Counter()
    dates: set[str] = set()
    with warehouse.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            session = row[_COLUMNS["date"]]
            if not WINDOW_START <= session <= WINDOW_END:
                continue
            code = row[_COLUMNS["code"]]
            dates.add(session)
            sessions[code] += 1
            if row[_COLUMNS["halt"]].strip() != "0":
                halts[code] += 1
            try:
                traded[code] += int(row[_COLUMNS["value"]] or 0)
            except ValueError:
                continue
    total = max(sessions.values())
    companies = _companies(master)
    clean = [
        code
        for code, seen in sessions.items()
        if seen == total and halts[code] == 0 and code in companies
    ]
    ranked = sorted(clean, key=lambda code: -traded[code])
    return ranked[:INSTRUMENT_COUNT], sorted(dates)


def build(
    project_root: Path,
    warehouse: Path = WAREHOUSE,
    master: Path = INSTRUMENT_MASTER,
) -> SamplePanel:
    instruments, sessions = _select(warehouse, master)
    if len(instruments) < INSTRUMENT_COUNT:
        raise ValueError(f"warehouse yielded only {len(instruments)} usable instruments")
    selected = set(instruments)
    late_listed, delisted = instruments[-1], instruments[-2]

    rows: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    with warehouse.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            session = row[_COLUMNS["date"]]
            code = row[_COLUMNS["code"]]
            if code not in selected or not WINDOW_START <= session <= WINDOW_END:
                continue
            factor = Decimal(row[_COLUMNS["adjust"]] or "1")
            rows[code][session] = {
                field: (Decimal(row[_COLUMNS[field]] or "0") * factor)
                for field in ("open", "high", "low", "close")
            } | {"volume": int(row[_COLUMNS["volume"]] or 0)}

    live_from = {code: 0 for code in instruments}
    live_to = {code: len(sessions) for code in instruments}
    live_from[late_listed] = LATE_SESSIONS
    live_to[delisted] = len(sessions) - DEAD_SESSIONS

    observations: list[dict[str, object]] = []
    execution: list[dict[str, object]] = []
    for code in instruments:
        for index, session in enumerate(sessions):
            values = rows[code].get(session)
            if values is None:
                continue
            listed = live_from[code] <= index < live_to[code]
            stamp = _available_at(session)
            if listed:
                observations.append(
                    {
                        "available_at": stamp,
                        "instrument": code,
                        "open": values["open"],
                        "high": values["high"],
                        "low": values["low"],
                        "close": values["close"],
                        "volume": values["volume"],
                    }
                )
            # The execution table outlives the observations for the delisted name so the closing
            # trade has a price; afterwards the row is gone exactly as the observation is.
            winding_down = (
                code == delisted and live_to[code] <= index < live_to[code] + WIND_DOWN_SESSIONS
            )
            if listed or winding_down:
                execution.append(
                    {
                        "trade_at": stamp,
                        "instrument": code,
                        "is_tradable": True,
                        "close": values["close"],
                    }
                )

    target = project_root / "sample"
    target.mkdir(parents=True, exist_ok=True)
    observations_path = target / "observations.parquet"
    execution_path = target / "execution.parquet"
    stamp_type = pa.timestamp("us", tz="UTC")
    observation_schema = pa.schema(
        [
            ("available_at", stamp_type),
            ("instrument", pa.string()),
            ("open", PRICE_TYPE),
            ("high", PRICE_TYPE),
            ("low", PRICE_TYPE),
            ("close", PRICE_TYPE),
            ("volume", pa.int64()),
        ]
    )
    execution_schema = pa.schema(
        [
            ("trade_at", stamp_type),
            ("instrument", pa.string()),
            ("is_tradable", pa.bool_()),
            ("close", PRICE_TYPE),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(observations, schema=observation_schema),
        observations_path,
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(execution, schema=execution_schema),
        execution_path,
        compression="zstd",
    )
    return SamplePanel(
        observations=observations_path,
        execution=execution_path,
        instruments=tuple(instruments),
        late_listed=late_listed,
        delisted=delisted,
        sessions=tuple(sessions),
    )
