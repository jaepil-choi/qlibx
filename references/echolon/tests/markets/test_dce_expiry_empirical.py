"""Offline DCE rule falsifier against the authoritative p2_v4 panel."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from echolon.markets.empirical_expiry import empirical_episodes
from echolon.markets.expiry import last_trade_date
from echolon.markets.shfe.trading_calendar import TradingCalendar

DCE_INSTRUMENTS = ("c", "p", "pp", "eg", "jd", "i", "l", "m", "v", "y")


def test_dce_encoded_rule_reproduces_at_least_95pct_empirical_last_trades(
    p2_v4_panel: Path,
) -> None:
    snapshot = p2_v4_panel

    rows = []
    for instrument in DCE_INSTRUMENTS:
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
        delivery_year, delivery_month = _delivery_month(str(contract))
        # A delivery month still in progress at the panel end is not expired.
        if (delivery_year, delivery_month) >= (panel_end.year, panel_end.month):
            continue
        empirical = episode[-1]
        source_episodes.add((str(contract), episode[0], empirical))
        predicted = last_trade_date(str(contract), "DCE", calendar)
        results.append((str(contract), empirical, predicted))

    bundled_episodes = {
        (contract, episode.first_observation, episode.last_trade)
        for contract in contracts["contract"].astype(str).unique()
        for episode in empirical_episodes(contract)
        if episode.exchange == "DCE"
    }
    assert bundled_episodes == source_episodes

    matches = sum(empirical == predicted for _, empirical, predicted in results)
    assert len(results) == 1068
    assert matches == 1022
    assert matches / len(results) >= 0.95


def _delivery_month(contract: str) -> tuple[int, int]:
    match = re.fullmatch(r"[A-Za-z]+(\d{2})(\d{2})", contract)
    if match is None:
        raise ValueError(f"unexpected DCE contract identifier: {contract}")
    return 2000 + int(match.group(1)), int(match.group(2))


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
