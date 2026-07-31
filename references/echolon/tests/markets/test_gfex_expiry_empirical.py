"""GFEX empirical-episode falsifiers (panel-v5, FV3 WP-X1b).

GFEX has no encoded last-trade rule and none is guessed (trap T7): support is
bundled empirical episodes derived from delivered contract bars, plus strict
refusal for any contract beyond the observed data (the defect-#10 pattern).

The independent re-derivation here reads the raw ``.csv.gz`` bars WITHOUT reusing
``scripts/build_gfex_expiry_data.py`` — its own epoch->Beijing conversion and
episode logic — so a builder bug cannot hide behind a matching builder-derived
expectation. The hand-pinned anchors are the ground truth of last resort.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import re
from importlib.resources import files
from pathlib import Path

import pytest

from echolon.markets.empirical_expiry import empirical_episode, empirical_episodes
from echolon.markets.expiry import days_to_last_trade, last_trade_date
from echolon.markets.gfex_calendar import load_gfex_trading_calendar

GFEX_PRODUCTS = ("si", "lc", "ps", "pt", "pd")
EXPECTED_GFEX_EPISODES = 80

# Hand-pinned from the raw contract files (first/last observed Beijing date).
PINNED_ANCHORS = {
    "SI2308": (dt.date(2022, 12, 22), dt.date(2023, 8, 14)),
    "LC2401": (dt.date(2023, 7, 21), dt.date(2024, 1, 15)),
    "PS2506": (dt.date(2024, 12, 26), dt.date(2025, 6, 16)),
    "PT2606": (dt.date(2025, 11, 27), dt.date(2026, 6, 12)),
    "PD2606": (dt.date(2025, 11, 27), dt.date(2026, 6, 12)),
}


def _bundled_gfex() -> set[tuple[str, dt.date, dt.date]]:
    resource = files("echolon.markets").joinpath("data/empirical_last_trades.csv")
    with resource.open("r", encoding="utf-8", newline="") as handle:
        return {
            (row["contract"],
             dt.date.fromisoformat(row["first_observation"]),
             dt.date.fromisoformat(row["last_trade"]))
            for row in csv.DictReader(handle)
            if row["exchange"] == "GFEX"
        }


def test_pinned_gfex_anchors_are_bundled_exactly() -> None:
    bundled = _bundled_gfex()
    for contract, (first, last) in PINNED_ANCHORS.items():
        assert (contract, first, last) in bundled, contract
        # And reachable through the public episode lookup at its own last day.
        episode = empirical_episode(contract, last)
        assert episode is not None and episode.exchange == "GFEX"
        assert (episode.first_observation, episode.last_trade) == (first, last)


def test_bundled_gfex_episode_keys_are_unambiguous() -> None:
    """Every observed GFEX contract resolves to exactly one episode, and no GFEX
    identifier collides with a non-GFEX bundled key (4-digit codes do not repeat
    over 2022-12..2026-07)."""
    bundled = _bundled_gfex()
    per_contract: dict[str, int] = {}
    for contract, _first, _last in bundled:
        per_contract[contract] = per_contract.get(contract, 0) + 1
    assert all(count == 1 for count in per_contract.values()), per_contract
    assert len(bundled) == EXPECTED_GFEX_EPISODES

    for contract in per_contract:
        episodes = empirical_episodes(contract)
        exchanges = {episode.exchange for episode in episodes}
        assert exchanges == {"GFEX"}, (contract, exchanges)


def test_gfex_beyond_data_contract_strictly_refuses() -> None:
    calendar = load_gfex_trading_calendar()
    # si2609 (delivery 2026-09) is beyond the observed data: no bundled episode.
    assert empirical_episode("si2609", dt.date(2026, 7, 10)) is None
    with pytest.raises(NotImplementedError, match="GFEX"):
        last_trade_date("si2609", "GFEX", object())
    with pytest.raises(NotImplementedError, match="GFEX"):
        days_to_last_trade("si2609", "GFEX", dt.date(2026, 7, 10), calendar)


def test_gfex_days_to_last_trade_uses_bundled_episode() -> None:
    calendar = load_gfex_trading_calendar()
    assert days_to_last_trade("SI2308", "GFEX", dt.date(2023, 8, 14), calendar) == 0
    assert days_to_last_trade("SI2308", "GFEX", dt.date(2023, 8, 1), calendar) > 0
    assert days_to_last_trade("SI2308", "GFEX", dt.date(2023, 8, 15), calendar) < 0


def test_independent_raw_rederivation_matches_bundled(gfex_raw_bars: Path) -> None:
    derived = _raw_gfex_episodes(gfex_raw_bars)
    assert derived == _bundled_gfex()
    assert len(derived) == EXPECTED_GFEX_EPISODES


# --------------------------------------------------------------------------- #
# Independent raw derivation (deliberately NOT importing the builder module).
# --------------------------------------------------------------------------- #
def _beijing_date(epoch_ms: int) -> dt.date:
    return (dt.datetime(1970, 1, 1)
            + dt.timedelta(milliseconds=epoch_ms, hours=8)).date()


def _episodes(dates: list[dt.date]) -> list[list[dt.date]]:
    episodes: list[list[dt.date]] = []
    start = 0
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days > 180:
            episodes.append(dates[start:index])
            start = index
    episodes.append(dates[start:])
    return episodes


def _delivery_month(contract: str) -> tuple[int, int]:
    match = re.fullmatch(r"[A-Z]+(\d{2})(\d{2})", contract)
    assert match is not None, contract
    return 2000 + int(match.group(1)), int(match.group(2))


def _raw_gfex_episodes(bars_root: Path) -> set[tuple[str, dt.date, dt.date]]:
    contract_dates: dict[str, set[dt.date]] = {}
    calendar: set[dt.date] = set()
    for product in GFEX_PRODUCTS:
        for path in sorted((bars_root / product).glob("*.csv.gz")):
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    contract = row["symbol"].strip().split(".")[0].upper()
                    day = _beijing_date(int(row["time"]))
                    contract_dates.setdefault(contract, set()).add(day)
                    calendar.add(day)
    panel_end = max(calendar)
    records: set[tuple[str, dt.date, dt.date]] = set()
    for contract, days in contract_dates.items():
        for episode in _episodes(sorted(days)):
            year, month = _delivery_month(contract)
            if (year, month) >= (panel_end.year, panel_end.month):
                continue
            records.add((contract, episode[0], episode[-1]))
    return records


