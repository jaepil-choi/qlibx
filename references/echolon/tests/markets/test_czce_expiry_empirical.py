"""Offline CZCE episode-keyed rule falsifier against the p2_v4 panel."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from echolon.markets.empirical_expiry import empirical_episodes
from echolon.markets.expiry import encoded_last_trade_date
from echolon.markets.shfe.trading_calendar import TradingCalendar

CZCE_INSTRUMENTS = ("cf", "rm", "sm", "sa", "sr", "sf", "fg", "ma", "oi", "ur", "ta")


def test_czce_encoded_rule_is_rejected_below_95pct_episode_bar(
    p2_v4_panel: Path,
) -> None:
    snapshot = p2_v4_panel

    rows = []
    for instrument in CZCE_INSTRUMENTS:
        frame = pd.read_csv(
            snapshot / "contracts" / f"{instrument}.csv",
            usecols=["date", "contract"],
        )
        frame["date"] = pd.to_datetime(frame["date"])
        rows.append(frame)
    contracts = pd.concat(rows, ignore_index=True)
    panel_end = contracts["date"].max().date()
    calendar = TradingCalendar()
    calendar._trading_days = set(contracts["date"].dt.date)
    calendar._calendar_loaded = True

    results: list[tuple[str, dt.date, dt.date]] = []
    source_episodes: set[tuple[str, dt.date, dt.date]] = set()
    for contract, episode in _episodes(contracts):
        year, month = _delivery_month(contract, episode[-1])
        if (year, month) >= (panel_end.year, panel_end.month):
            continue
        empirical = episode[-1]
        source_episodes.add((contract, episode[0], empirical))
        predicted = encoded_last_trade_date(
            contract, "CZCE", calendar, delivery_year=year
        )
        results.append((contract, empirical, predicted))

    bundled_episodes = {
        (contract, episode.first_observation, episode.last_trade)
        for contract in contracts["contract"].astype(str).unique()
        for episode in empirical_episodes(contract)
        if episode.exchange == "CZCE"
    }
    assert bundled_episodes == source_episodes

    matches = sum(empirical == predicted for _, empirical, predicted in results)
    assert len(results) == 1037
    assert matches == 562
    assert matches / len(results) < 0.95


def _episodes(frame: pd.DataFrame) -> list[tuple[str, list[dt.date]]]:
    episodes: list[tuple[str, list[dt.date]]] = []
    for contract, group in frame.groupby("contract"):
        dates = sorted(group["date"].dt.date.unique())
        start = 0
        for index in range(1, len(dates)):
            if (dates[index] - dates[index - 1]).days > 180:
                episodes.append((str(contract), dates[start:index]))
                start = index
        episodes.append((str(contract), dates[start:]))
    return episodes


def _delivery_month(contract: str, empirical: dt.date) -> tuple[int, int]:
    match = re.fullmatch(r"[A-Za-z]+(\d)(\d{2})", contract)
    if match is None:
        raise ValueError(f"unexpected CZCE contract identifier: {contract}")
    year_digit, month = int(match.group(1)), int(match.group(2))
    candidates = [
        year
        for year in range(empirical.year - 2, empirical.year + 3)
        if year % 10 == year_digit
    ]
    return min(candidates, key=lambda year: abs(year - empirical.year)), month
