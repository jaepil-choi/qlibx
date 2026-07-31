"""CZCE ap/cj/pk empirical-episode falsifiers (panel-v5, FV3 round-3 backfill).

Panel-v5 adds three CZCE products (ap/cj/pk) absent from p2_v4; their observed contract
episodes must be bundled because the strict episode clock REFUSES uncovered four-digit
live identifiers with
:class:`NotImplementedError` (CZCE is empirical-only; the defect-#10 pattern).  This
module is the permanent falsifier for the add-only backfill of those episodes.

Three independent guards, per the round-3 dispatch:

* Hand-pinned anchors (first/last observed Beijing date) for several new contracts,
  read from the ground-truth raw bars, reachable through the public episode lookup.
* ADD-ONLY: stripping every ap/cj/pk row from the LIVE bundled table must reproduce the
  PRE-backfill file byte-for-byte (its sha at the parent commit), so no incumbent, GFEX,
  or other-exchange row was touched — only ap/cj/pk rows were added.
* Strict refusal preserved BEYOND the data: a CZCE contract with no bundled episode still
  refuses (no guessed rule sneaks in behind the new rows).

The independent raw re-derivation deliberately does NOT import
``scripts/build_czce_new_products_expiry_data.py`` so a builder bug cannot hide behind a
matching builder-derived expectation.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
from importlib.resources import files
from pathlib import Path

import pandas as pd
import pytest

from echolon.markets.empirical_expiry import empirical_episode, empirical_episodes
from echolon.markets.expiry import days_to_last_trade, last_trade_date
from echolon.markets.shfe.trading_calendar import TradingCalendar

NEW_PRODUCTS = ("ap", "cj", "pk")
EXPECTED_COUNTS = {"AP": 71, "CJ": 52, "PK": 46}
EXPECTED_TOTAL = 169
PRE_ALIVE_COMPLETION_SHA = "19689da54bc5439be7dd7dab291ea3c4a2021166225f954867fe97d7a5321774"
ALIVE_COMPLETION_COUNTS = {"AP": 14, "CJ": 12, "PK": 14}
ALIVE_COMPLETION_TOTAL = 40

# sha of echolon/markets/data/empirical_last_trades.csv at the parent commit (post-GFEX,
# pre-ap/cj/pk) — the exact bytes the ap/cj/pk backfill must leave untouched.
PRE_BACKFILL_SHA = "d29c816ca513d1f98149f0c8c800e8f4e07a1f2944e696254dccecaa808a597d"

# Hand-pinned from the raw contract files (first/last observed Beijing date).  The last
# three are the exact contracts the live episode clock refused before this backfill.
PINNED_ANCHORS = {
    "AP1805": (dt.date(2017, 12, 22), dt.date(2018, 5, 15)),
    "AP1810": (dt.date(2017, 12, 22), dt.date(2018, 10, 19)),
    "CJ1912": (dt.date(2019, 4, 30), dt.date(2019, 12, 13)),
    "PK2110": (dt.date(2021, 2, 1), dt.date(2021, 10, 21)),
    "AP2204": (dt.date(2021, 4, 16), dt.date(2022, 4, 18)),
    "CJ2205": (dt.date(2021, 5, 20), dt.date(2022, 5, 18)),
    "PK2210": (dt.date(2021, 10, 22), dt.date(2022, 10, 21)),
}


def _csv_bytes() -> bytes:
    return files("echolon.markets").joinpath("data/empirical_last_trades.csv").read_bytes()


def _bundled_new_czce() -> set[tuple[str, dt.date, dt.date]]:
    resource = files("echolon.markets").joinpath("data/empirical_last_trades.csv")
    with resource.open("r", encoding="utf-8", newline="") as handle:
        return {
            (row["contract"],
             dt.date.fromisoformat(row["first_observation"]),
             dt.date.fromisoformat(row["last_trade"]))
            for row in csv.DictReader(handle)
            if row["exchange"] == "CZCE" and _product_of(row["contract"]) in NEW_PRODUCTS
        }


def _product_of(contract: str) -> str:
    return re.match(r"[A-Za-z]+", contract).group(0).lower()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strip_new_czce(raw: bytes) -> bytes:
    """Remove every CZCE ap/cj/pk row, mirroring ``grep -vE '^CZCE,(AP|CJ|PK)[0-9]'``
    byte-for-byte (line terminators and any missing final newline preserved)."""
    pattern = re.compile(rb"^CZCE,(AP|CJ|PK)[0-9]")
    segments = raw.split(b"\n")
    kept = [seg for seg in segments if pattern.match(seg) is None]
    return b"\n".join(kept)


def _strip_alive_completion(raw: bytes) -> bytes:
    """Remove only the panel-end ap/cj/pk completion layered onto the 129-row backfill."""
    kept: list[bytes] = []
    for segment in raw.split(b"\n"):
        fields = segment.split(b",")
        is_completion = (
            len(fields) == 4
            and re.match(rb"^(AP|CJ|PK)[0-9]", fields[1]) is not None
            and fields[2] >= b"2025-07-15"
        )
        if not is_completion:
            kept.append(segment)
    return b"\n".join(kept)


def test_pinned_anchors_are_bundled_exactly() -> None:
    bundled = _bundled_new_czce()
    for contract, (first, last) in PINNED_ANCHORS.items():
        assert (contract, first, last) in bundled, contract
        episode = empirical_episode(contract, last)
        assert episode is not None and episode.exchange == "CZCE"
        assert (episode.first_observation, episode.last_trade) == (first, last)


def test_bundled_new_czce_keys_are_unambiguous_and_counted() -> None:
    """Every observed ap/cj/pk contract resolves to exactly one episode; the per-product
    and total counts are pinned; and no ap/cj/pk key collides with any other bundled key
    (the four-digit codes do not repeat across the observed 2017-2026 window)."""
    bundled = _bundled_new_czce()
    per_contract: dict[str, int] = {}
    per_product: dict[str, int] = {}
    for contract, _first, _last in bundled:
        per_contract[contract] = per_contract.get(contract, 0) + 1
        prod = _product_of(contract).upper()
        per_product[prod] = per_product.get(prod, 0) + 1
    assert all(count == 1 for count in per_contract.values()), per_contract
    assert per_product == EXPECTED_COUNTS
    assert len(bundled) == EXPECTED_TOTAL

    for contract in per_contract:
        exchanges = {episode.exchange for episode in empirical_episodes(contract)}
        assert exchanges == {"CZCE"}, (contract, exchanges)


def test_backfill_is_add_only_nonnew_subset_matches_pre_backfill_pin() -> None:
    """Strip every ap/cj/pk row from the LIVE file; the remainder must hash to the
    pre-backfill file.  Proves the backfill added ap/cj/pk rows and touched nothing else
    — no incumbent CZCE, GFEX, or other-exchange byte moved."""
    assert _sha(_strip_new_czce(_csv_bytes())) == PRE_BACKFILL_SHA


def test_alive_completion_is_add_only_over_129_row_backfill() -> None:
    """Strip only the 40 panel-end rows and recover the prior authorized whole file."""
    live = _csv_bytes()
    stripped = _strip_alive_completion(live)
    assert _sha(stripped) == PRE_ALIVE_COMPLETION_SHA
    added = [row for row in live.split(b"\n") if row and row not in set(stripped.split(b"\n"))]
    per_product = {product: 0 for product in ALIVE_COMPLETION_COUNTS}
    for row in added:
        product = _product_of(row.decode().split(",")[1]).upper()
        per_product[product] += 1
    assert per_product == ALIVE_COMPLETION_COUNTS
    assert len(added) == ALIVE_COMPLETION_TOTAL


def test_add_only_falsifier_has_teeth_nonnew_edit_is_caught() -> None:
    """The subset check CAN fail: mutating a single non-ap/cj/pk byte breaks the pre-backfill
    equality even though the ap/cj/pk rows are untouched."""
    stripped = _strip_new_czce(_csv_bytes())
    assert b"GFEX," in stripped
    doctored = stripped.replace(b"GFEX,", b"XFEX,", 1)
    assert doctored != stripped
    assert _sha(doctored) != PRE_BACKFILL_SHA


def test_exactly_the_new_rows_were_added_nothing_removed() -> None:
    live = _csv_bytes()
    stripped = _strip_new_czce(live)  # == pre-backfill file (asserted above)
    live_rows = [r for r in live.split(b"\n") if r]
    old_rows = [r for r in stripped.split(b"\n") if r]
    old_set = set(old_rows)
    added = [r for r in live_rows if r not in old_set]
    assert len(added) == EXPECTED_TOTAL
    assert all(re.match(rb"^CZCE,(AP|CJ|PK)[0-9]", r) for r in added)
    # Nothing removed: every pre-backfill row still present.
    live_set = set(live_rows)
    assert all(r in live_set for r in old_rows)


def test_beyond_data_contract_strictly_refuses() -> None:
    """A CZCE contract with no bundled episode still refuses (empirical-only, no guessed
    rule).  AP2801 (delivery 2028-01) is beyond the observed data."""
    assert empirical_episode("AP2801", dt.date(2026, 7, 10)) is None
    with pytest.raises(NotImplementedError, match="CZCE"):
        last_trade_date("AP2801", "CZCE", object())
    calendar = _business_calendar("2026-07-01", "2026-07-31")
    with pytest.raises(NotImplementedError, match="CZCE"):
        days_to_last_trade("AP2801", "CZCE", dt.date(2026, 7, 10), calendar)


def test_days_to_last_trade_uses_bundled_episode() -> None:
    calendar = _business_calendar("2018-09-01", "2018-11-30")
    assert days_to_last_trade("AP1810", "CZCE", dt.date(2018, 10, 19), calendar) == 0
    assert days_to_last_trade("AP1810", "CZCE", dt.date(2018, 10, 1), calendar) > 0
    assert days_to_last_trade("AP1810", "CZCE", dt.date(2018, 10, 22), calendar) < 0


def test_independent_panel_rederivation_matches_bundled(p2_v5_contracts: Path) -> None:
    derived = _panel_new_czce_episodes(p2_v5_contracts)
    assert derived == _bundled_new_czce()
    assert len(derived) == EXPECTED_TOTAL


# --------------------------------------------------------------------------- #
# Independent panel derivation (deliberately NOT importing the builder module).
# --------------------------------------------------------------------------- #
def _episodes(dates: list[dt.date]) -> list[list[dt.date]]:
    episodes: list[list[dt.date]] = []
    start = 0
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days > 180:
            episodes.append(dates[start:index])
            start = index
    episodes.append(dates[start:])
    return episodes


def _panel_new_czce_episodes(contracts_root: Path) -> set[tuple[str, dt.date, dt.date]]:
    contract_dates: dict[str, set[dt.date]] = {}
    for product in NEW_PRODUCTS:
        with (contracts_root / f"{product}.csv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                contract = row["contract"].strip().upper()
                contract_dates.setdefault(contract, set()).add(dt.date.fromisoformat(row["date"]))
    records: set[tuple[str, dt.date, dt.date]] = set()
    for contract, days in contract_dates.items():
        for episode in _episodes(sorted(days)):
            records.add((contract, episode[0], episode[-1]))
    return records


def _business_calendar(start: str, end: str) -> TradingCalendar:
    calendar = TradingCalendar()
    calendar._trading_days = {value.date() for value in pd.bdate_range(start, end)}
    calendar._calendar_loaded = True
    return calendar
