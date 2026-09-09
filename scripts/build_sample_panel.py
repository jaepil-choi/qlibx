"""Cut the shipped sample panel from the local warehouse, then make it synthetic.

Developer-only (record `172`). Reads `data/DW` -- a warehouse a user never has -- and writes the
panel `vqapr new sample` ships, under `src/vqapr/agent/sample/data/`. Run it once when the
sample's shape changes; commit what it writes. The package never runs this.

What makes the panel synthetic, so that it can be committed and shipped without redistributing
market data: every instrument code is replaced (`K000001`..), every company name is twisted by one
syllable or letter, every price is multiplied by a per-instrument scale in [1.5, 2.5] and a
per-observation jitter of +-0.3 % (so the return series no longer match the source either), and
volumes are scaled per instrument. What is kept is the SHAPE the sample exists to show: real KRX
sessions over 2022-2024, one name that lists 200 sessions late, one that stops 250 sessions early
and stays tradable for three sessions after its last observation so the position can be closed.

    uv run python scripts/build_sample_panel.py
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

PRICE_TYPE = pa.float64()
"""A price is a DOUBLE, as the sample's declaration says it is (`docs/issues/archive/088`).

This was `decimal128(18, 4)` until 2026-09-08, on the reasoning that prices should stay exact.
What it did instead was hand every model `Decimal` from a field registered as DOUBLE and make the
sample the one parquet a user would never produce. The transform below still runs in `Decimal`
and quantizes to `QUANTUM`, so the digits are exact; the write is the DOUBLE the dataset
declares, and a model that wants exact arithmetic crosses once with `Decimal(str(v))`."""

WAREHOUSE = Path("data/DW/fng_stock_daily_prices.csv")
INSTRUMENT_MASTER = Path("data/DW/DW_FNG_FGSC종목_20200101-20260430.csv")
"""Names of listed shares. Codes absent here are funds rather than companies."""
TARGET = Path("src/vqapr/agent/sample/data")
"""Where the package keeps the panel; `vqapr new sample` copies from here."""

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

SEED = 172
"""The record that introduced the synthetic panel. Fixed so the generator is reproducible."""
SCALE_RANGE = (Decimal("1.5"), Decimal("2.5"))
JITTER = Decimal("0.003")
VOLUME_RANGE = (0.5, 2.0)
QUANTUM = Decimal("0.0001")

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

_VOWEL_TWIST = {
    "ㅓ": "ㅜ", "ㅏ": "ㅗ", "ㅗ": "ㅏ", "ㅜ": "ㅓ", "ㅡ": "ㅣ", "ㅣ": "ㅡ", "ㅐ": "ㅔ", "ㅔ": "ㅐ"
}
_JAMO_VOWELS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_LATIN_TWIST = {"G": "C", "S": "Z", "K": "Q", "H": "N", "L": "I", "D": "B", "T": "F", "P": "R"}


@dataclass(frozen=True, slots=True)
class Selection:
    codes: list[str]
    sessions: list[str]
    names: dict[str, str]


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


def _select(warehouse: Path, master: Path) -> Selection:
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
    ranked = sorted(clean, key=lambda code: -traded[code])[:INSTRUMENT_COUNT]
    return Selection(ranked, sorted(dates), {code: companies[code] for code in ranked})


def _twist_name(name: str) -> str:
    """One syllable or letter changed, so the name is recognisably not a company's.

    `삼성전자` -> `삼숭전자`, `LG에너지솔루션` -> `LC에너지솔루션`: the owner's examples. The second
    Hangul syllable's vowel is swapped when there is one; otherwise the second Latin letter.
    """
    chars = list(name)
    hangul = [i for i, ch in enumerate(chars) if "가" <= ch <= "힣"]
    if len(hangul) >= 2:
        index = hangul[1]
        code = ord(chars[index]) - 0xAC00
        initial, vowel, final = code // 588, (code % 588) // 28, code % 28
        twisted = _VOWEL_TWIST.get(_JAMO_VOWELS[vowel], "ㅜ")
        chars[index] = chr(0xAC00 + initial * 588 + _JAMO_VOWELS.index(twisted) * 28 + final)
        return "".join(chars)
    latin = [i for i, ch in enumerate(chars) if ch.isascii() and ch.isalpha()]
    if len(latin) >= 2:
        index = latin[1]
        chars[index] = _LATIN_TWIST.get(chars[index].upper(), "X")
        return "".join(chars)
    return name + "*"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def build(
    warehouse: Path = WAREHOUSE,
    master: Path = INSTRUMENT_MASTER,
    target: Path = TARGET,
) -> dict[str, object]:
    selection = _select(warehouse, master)
    if len(selection.codes) < INSTRUMENT_COUNT:
        raise ValueError(f"warehouse yielded only {len(selection.codes)} usable instruments")
    real_codes = selection.codes
    sessions = selection.sessions
    fake = {code: f"K{index + 1:06d}" for index, code in enumerate(real_codes)}
    late_listed, delisted = real_codes[-1], real_codes[-2]

    rng = random.Random(SEED)
    scale = {
        code: _quantize(SCALE_RANGE[0] + (SCALE_RANGE[1] - SCALE_RANGE[0]) * Decimal(rng.random()))
        for code in real_codes
    }
    volume_scale = {code: rng.uniform(*VOLUME_RANGE) for code in real_codes}

    selected = set(real_codes)
    rows: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    with warehouse.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            session = row[_COLUMNS["date"]]
            code = row[_COLUMNS["code"]]
            if code not in selected or not WINDOW_START <= session <= WINDOW_END:
                continue
            factor = Decimal(row[_COLUMNS["adjust"]] or "1")
            # One jitter per (name, session): the execution close must equal the observed close.
            jitter = Decimal(1) + JITTER * Decimal(rng.uniform(-1, 1))
            multiplier = scale[code] * jitter * factor
            rows[code][session] = {
                field: float(_quantize(Decimal(row[_COLUMNS[field]] or "0") * multiplier))
                for field in ("open", "high", "low", "close")
            } | {"volume": int(int(row[_COLUMNS["volume"]] or 0) * volume_scale[code])}

    live_from = {code: 0 for code in real_codes}
    live_to = {code: len(sessions) for code in real_codes}
    live_from[late_listed] = LATE_SESSIONS
    live_to[delisted] = len(sessions) - DEAD_SESSIONS

    observations: list[dict[str, object]] = []
    execution: list[dict[str, object]] = []
    for code in real_codes:
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
                        "instrument": fake[code],
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
                        "instrument": fake[code],
                        "is_tradable": True,
                        "close": values["close"],
                    }
                )

    target.mkdir(parents=True, exist_ok=True)
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
        target / "observations.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(execution, schema=execution_schema),
        target / "execution.parquet",
        compression="zstd",
    )
    with (target / "instruments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["instrument", "name"])
        for code in real_codes:
            writer.writerow([fake[code], _twist_name(selection.names[code])])
    panel = {
        "synthetic": True,
        "instruments": [fake[code] for code in real_codes],
        "late_listed": fake[late_listed],
        "delisted": fake[delisted],
        "sessions": len(sessions),
        "first_session": sessions[0],
        "last_session": sessions[-1],
        "late_sessions": LATE_SESSIONS,
        "dead_sessions": DEAD_SESSIONS,
        "wind_down_sessions": WIND_DOWN_SESSIONS,
        "observations": len(observations),
        "execution_rows": len(execution),
        "generator": "scripts/build_sample_panel.py",
        "seed": SEED,
    }
    (target / "panel.json").write_text(json.dumps(panel, indent=2) + "\n", encoding="utf-8")
    return panel


if __name__ == "__main__":
    summary = build()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
