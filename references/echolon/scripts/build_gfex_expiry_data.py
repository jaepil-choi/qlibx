"""Build GFEX empirical last-trade episodes and the GFEX trading calendar.

GFEX (Guangzhou Futures Exchange) has no encoded last-trade convention in this
repository and, per the module discipline in ``echolon/markets/expiry.py``, none
is guessed: CZCE's guessed rule already failed its episode-keyed validation bar.
GFEX support is therefore derived purely from observed contract data, exactly as
CZCE/DCE/SHFE episodes were derived by ``build_empirical_last_trade_data.py``.

Source: per-contract daily bars ``.csv.gz`` delivered under
``<bars_root>/{si,lc,ps,pt,pd}/*.csv.gz`` (xtdata_expansion_20260711). The bar
``time`` column is epoch-milliseconds in UTC; a single shared helper converts it
to the Beijing trade date (the midnight-Beijing bar timestamp lands at 16:00 UTC
the previous day, so a naive UTC ``.date()`` is one day early — trap T8).

Two artifacts are written:

* GFEX rows are merged (idempotently) into
  ``echolon/markets/data/empirical_last_trades.csv`` with the same
  ``exchange,contract,first_observation,last_trade`` schema and the same
  180-day episode-gap and delivery-month expiry filters as the CZCE/DCE builder.
* The union of every observed GFEX bar date is written to
  ``echolon/markets/data/gfex_trading_calendar.csv`` (``date`` column).

Contract identifiers are stored WITHOUT the ``.GF`` exchange suffix (e.g.
``SI2308``) so they parse through the same four-digit contract grammar as the
other exchanges and never collide with a non-GFEX bundled key.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import re
from pathlib import Path

GFEX_PRODUCTS = ("si", "lc", "ps", "pt", "pd")
EPISODE_GAP_DAYS = 180
_UNIX_EPOCH = dt.datetime(1970, 1, 1)
_BEIJING_OFFSET = dt.timedelta(hours=8)

_REPO_ROOT = Path(__file__).resolve().parents[1]
# No default bars root: the raw bars live in an artifact store whose location and
# name are the caller's to know, not this repo's. ``--bars-root`` is required so
# omitting it is an argparse error rather than a silent read of a guessed path.
_DEFAULT_EPISODES_CSV = _REPO_ROOT / "echolon/markets/data/empirical_last_trades.csv"
_DEFAULT_CALENDAR_CSV = _REPO_ROOT / "echolon/markets/data/gfex_trading_calendar.csv"

_EPISODE_FIELDS = ("exchange", "contract", "first_observation", "last_trade")


def beijing_date_from_epoch_ms(epoch_ms: int) -> dt.date:
    """Convert an epoch-millisecond UTC bar timestamp to its Beijing trade date.

    This is the single conversion point for trap T8: China Standard Time is a
    fixed UTC+8 (no DST since 1991), so shifting by eight hours before taking the
    calendar date recovers the true trade date from a midnight-Beijing bar stamp.
    """
    return (_UNIX_EPOCH + dt.timedelta(milliseconds=epoch_ms) + _BEIJING_OFFSET).date()


def _contract_trade_dates(path: Path) -> tuple[str, list[dt.date]]:
    """Return the suffix-stripped contract id and its sorted observed dates."""
    dates: set[dt.date] = set()
    contract: str | None = None
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"].strip()
            contract = symbol.split(".")[0].upper()
            dates.add(beijing_date_from_epoch_ms(int(row["time"])))
    if contract is None:
        raise ValueError(f"no bar rows in {path}")
    return contract, sorted(dates)


def _episodes(dates: list[dt.date]) -> list[list[dt.date]]:
    """Split observations into episodes whenever a gap exceeds 180 days."""
    episodes: list[list[dt.date]] = []
    start = 0
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days > EPISODE_GAP_DAYS:
            episodes.append(dates[start:index])
            start = index
    episodes.append(dates[start:])
    return episodes


def _delivery_month(contract: str) -> tuple[int, int]:
    """Return the (year, month) delivery month of a four-digit GFEX contract."""
    match = re.fullmatch(r"[A-Z]+(\d{2})(\d{2})", contract)
    if match is None:
        raise ValueError(f"unexpected GFEX contract identifier: {contract}")
    year_digits = int(match.group(1))
    year = 2000 + year_digits if year_digits <= 50 else 1900 + year_digits
    return year, int(match.group(2))


def derive_gfex(bars_root: Path) -> tuple[list[dict[str, str]], list[dt.date]]:
    """Return expired GFEX episode records and the full GFEX session calendar."""
    contract_dates: dict[str, list[dt.date]] = {}
    calendar: set[dt.date] = set()
    for product in GFEX_PRODUCTS:
        product_dir = bars_root / product
        for path in sorted(product_dir.glob("*.csv.gz")):
            contract, dates = _contract_trade_dates(path)
            if contract in contract_dates:
                raise ValueError(f"duplicate GFEX contract file for {contract}")
            contract_dates[contract] = dates
            calendar.update(dates)

    panel_end = max(calendar)
    records: list[dict[str, str]] = []
    for contract, dates in contract_dates.items():
        for episode in _episodes(dates):
            year, month = _delivery_month(contract)
            # A delivery month still in progress at the data cutoff is not expired.
            if (year, month) >= (panel_end.year, panel_end.month):
                continue
            records.append(
                {
                    "exchange": "GFEX",
                    "contract": contract,
                    "first_observation": episode[0].isoformat(),
                    "last_trade": episode[-1].isoformat(),
                }
            )
    return records, sorted(calendar)


def _merge_episodes(episodes_csv: Path, gfex_records: list[dict[str, str]]) -> int:
    """Replace GFEX rows in the bundled episode table, preserving other exchanges."""
    existing: list[dict[str, str]] = []
    if episodes_csv.exists():
        with episodes_csv.open("r", encoding="utf-8", newline="") as handle:
            existing = [
                row
                for row in csv.DictReader(handle)
                if row["exchange"] != "GFEX"
            ]
    merged = existing + gfex_records
    episodes_csv.parent.mkdir(parents=True, exist_ok=True)
    with episodes_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_EPISODE_FIELDS)
        writer.writeheader()
        writer.writerows(
            sorted(
                merged,
                key=lambda row: (
                    row["exchange"],
                    row["contract"],
                    row["first_observation"],
                ),
            )
        )
    return len(gfex_records)


def _write_calendar(calendar_csv: Path, calendar: list[dt.date]) -> None:
    calendar_csv.parent.mkdir(parents=True, exist_ok=True)
    with calendar_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date"])
        writer.writerows([day.isoformat()] for day in calendar)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bars-root",
        type=Path,
        required=True,
        help="Directory holding the raw GFEX daily-bar .csv.gz files, inside the "
        "caller's artifact store.",
    )
    parser.add_argument("--episodes-csv", type=Path, default=_DEFAULT_EPISODES_CSV)
    parser.add_argument("--calendar-csv", type=Path, default=_DEFAULT_CALENDAR_CSV)
    args = parser.parse_args()

    records, calendar = derive_gfex(args.bars_root)
    _merge_episodes(args.episodes_csv, records)
    _write_calendar(args.calendar_csv, calendar)
    print(
        f"wrote {len(records)} expired GFEX episodes and "
        f"{len(calendar)} GFEX sessions "
        f"({calendar[0]}..{calendar[-1]})"
    )


if __name__ == "__main__":
    main()
