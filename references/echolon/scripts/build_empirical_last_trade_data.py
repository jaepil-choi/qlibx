"""Build the FV2 episode-keyed empirical last-trade table from p2_v4."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from pathlib import Path

import pandas as pd

EXCHANGE_INSTRUMENTS = {
    "SHFE": ("ag", "al", "bu", "cu", "fu", "hc", "ni", "rb", "ru", "zn"),
    "CZCE": ("cf", "fg", "ma", "oi", "rm", "sa", "sf", "sm", "sr", "ta", "ur"),
    "DCE": ("c", "eg", "i", "jd", "l", "m", "p", "pp", "v", "y"),
}
EPISODE_GAP_DAYS = 180


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("panel", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    contracts_dir = args.panel / "contracts"
    frames: list[pd.DataFrame] = []
    exchanges: dict[str, str] = {}
    for exchange, instruments in EXCHANGE_INSTRUMENTS.items():
        for instrument in instruments:
            frame = pd.read_csv(
                contracts_dir / f"{instrument}.csv",
                usecols=["date", "contract"],
            )
            frame["date"] = pd.to_datetime(frame["date"])
            frames.append(frame)
            exchanges.update(
                {
                    str(contract).upper(): exchange
                    for contract in frame["contract"].unique()
                }
            )
    panel = pd.concat(frames, ignore_index=True)
    panel_end = panel["date"].max().date()

    records: list[dict[str, str]] = []
    for contract, group in panel.groupby("contract"):
        normalized = str(contract).upper()
        for episode in _episodes(sorted(group["date"].dt.date.unique())):
            year, month = _delivery_month(normalized, episode[-1])
            if (year, month) >= (panel_end.year, panel_end.month):
                continue
            records.append(
                {
                    "exchange": exchanges[normalized],
                    "contract": normalized,
                    "first_observation": episode[0].isoformat(),
                    "last_trade": episode[-1].isoformat(),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "exchange",
                "contract",
                "first_observation",
                "last_trade",
            ),
        )
        writer.writeheader()
        writer.writerows(
            sorted(
                records,
                key=lambda row: (
                    row["exchange"],
                    row["contract"],
                    row["first_observation"],
                ),
            )
        )
    print(f"wrote {len(records)} expired episodes through panel end {panel_end}")


def _episodes(dates: list[dt.date]) -> list[list[dt.date]]:
    episodes: list[list[dt.date]] = []
    start = 0
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days > EPISODE_GAP_DAYS:
            episodes.append(dates[start:index])
            start = index
    episodes.append(dates[start:])
    return episodes


def _delivery_month(contract: str, empirical: dt.date) -> tuple[int, int]:
    four_digit = re.fullmatch(r"[A-Z]+(\d{2})(\d{2})", contract)
    if four_digit is not None:
        year_digits = int(four_digit.group(1))
        year = 2000 + year_digits if year_digits <= 50 else 1900 + year_digits
        return year, int(four_digit.group(2))
    three_digit = re.fullmatch(r"[A-Z]+(\d)(\d{2})", contract)
    if three_digit is None:
        raise ValueError(f"unexpected contract identifier: {contract}")
    year_digit = int(three_digit.group(1))
    candidates = [
        year
        for year in range(empirical.year - 2, empirical.year + 3)
        if year % 10 == year_digit
    ]
    return min(candidates, key=lambda year: abs(year - empirical.year)), int(
        three_digit.group(2)
    )


if __name__ == "__main__":
    main()
