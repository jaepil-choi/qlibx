"""Build empirical last-trade episodes for the three new CZCE products ap/cj/pk.

Panel-v5 (FV3 round-3) adds three CZCE products — ap (apple), cj (jujube/red date),
pk (peanut) — that were absent from p2_v4 and therefore have NO rows in the bundled
``echolon/markets/data/empirical_last_trades.csv``.  Without episodes, the strict
episode clock REFUSES their four-digit live contracts with :class:`NotImplementedError`
(CZCE has no operational encoded rule; expired contracts are empirical-only).  This
builder backfills those episodes purely from observed contract bars — no guessed rule —
exactly as the incumbent CZCE/DCE/SHFE episodes (``build_empirical_last_trade_data.py``)
and the GFEX episodes (``build_gfex_expiry_data.py``) were derived.

Keying convention (the CZCE decade-repeat trap).  CZCE's three-digit exchange codes
repeat every decade (AP601 = Jan-2016 AND Jan-2026), so the bundled table is
EPISODE-keyed: the same code carries multiple rows disambiguated by ``first_observation``.
The contract identifier stored here is exactly the code carried in the delivered bar
``symbol`` (e.g. ``AP1805`` — a four-digit unified code — split from its ``.ZF`` suffix),
because that is the identifier panel-v5 presents to the episode clock verbatim for these
products.  The delivered set also contains native three-digit codes (``AP701``) for
currently-listed contracts.  Both representations are stored exactly as panel-v5
presents them: three-digit codes are decade-safe because lookup is episode-keyed, while
the four-digit rows let the empirical-only CZCE clock rank live unified codes without
guessing an expiry rule.  For a contract still alive at the panel cutoff, ``last_trade``
is its last observed panel date (an explicit beyond-calendar sentinel), not a projected
exchange last-trade date.

Source: the delivered panel-v5 contract frames under
``<panel_contracts_root>/{ap,cj,pk}.csv``.  These frames already contain the exact
contract identifiers and Beijing trade dates presented to the signal engine; using them
also respects panel QC exclusions (for example CJ2607/CJ607 end on 2026-07-09 in the
published panel although the delivered raw bar family contains a 2026-07-10 row).

The write is strictly ADD-ONLY: every existing row (all other exchanges AND the incumbent
CZCE products) is preserved byte-for-byte; only ap/cj/pk rows are (re)written, so re-runs
are idempotent.  The final table is re-sorted by (exchange, contract, first_observation),
the same key the incumbent and GFEX builders use.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
from pathlib import Path

NEW_PRODUCTS = ("ap", "cj", "pk")
EPISODE_GAP_DAYS = 180

_REPO_ROOT = Path(__file__).resolve().parents[1]
# No default contracts root: the panel lives in an artifact store whose location
# and name are the caller's to know, not this repo's. ``--panel-contracts-root``
# is required so omitting it is an argparse error rather than a silent read of a
# guessed path.
_DEFAULT_EPISODES_CSV = _REPO_ROOT / "echolon/markets/data/empirical_last_trades.csv"

_EPISODE_FIELDS = ("exchange", "contract", "first_observation", "last_trade")


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


def _product_of(contract: str) -> str:
    """Return the lowercase product prefix (leading letters) of a contract code."""
    match = re.match(r"[A-Za-z]+", contract)
    if match is None:
        raise ValueError(f"uncontract-like identifier: {contract}")
    return match.group(0).lower()


def derive_new_czce(panel_contracts_root: Path) -> list[dict[str, str]]:
    """Return observed episode records for the new CZCE products ap/cj/pk."""
    contract_dates: dict[str, set[dt.date]] = {}
    for product in NEW_PRODUCTS:
        path = panel_contracts_root / f"{product}.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                contract = row["contract"].strip().upper()
                contract_dates.setdefault(contract, set()).add(
                    dt.date.fromisoformat(row["date"])
                )

    records: list[dict[str, str]] = []
    for contract, dates in contract_dates.items():
        for episode in _episodes(sorted(dates)):
            records.append(
                {
                    "exchange": "CZCE",
                    "contract": contract,
                    "first_observation": episode[0].isoformat(),
                    "last_trade": episode[-1].isoformat(),
                }
            )
    return records


def _merge_episodes(episodes_csv: Path, new_records: list[dict[str, str]]) -> int:
    """Add-only merge: drop any existing ap/cj/pk CZCE rows, keep every other row, then
    append the new records and re-sort.  Preserves incumbent rows byte-for-byte and makes
    re-runs idempotent."""
    new_products = set(NEW_PRODUCTS)
    existing: list[dict[str, str]] = []
    if episodes_csv.exists():
        with episodes_csv.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["exchange"] == "CZCE" and _product_of(row["contract"]) in new_products:
                    continue
                existing.append(row)
    merged = existing + new_records
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
    return len(new_records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--panel-contracts-root",
        type=Path,
        required=True,
        help="Directory holding the panel-v5 per-product contract CSVs, inside "
        "the caller's artifact store.",
    )
    parser.add_argument("--episodes-csv", type=Path, default=_DEFAULT_EPISODES_CSV)
    args = parser.parse_args()

    records = derive_new_czce(args.panel_contracts_root)
    _merge_episodes(args.episodes_csv, records)
    per_product: dict[str, int] = {}
    for record in records:
        per_product[_product_of(record["contract"])] = (
            per_product.get(_product_of(record["contract"]), 0) + 1
        )
    summary = ", ".join(f"{p.upper()} {per_product.get(p, 0)}" for p in NEW_PRODUCTS)
    print(f"wrote {len(records)} observed CZCE ap/cj/pk episodes ({summary})")


if __name__ == "__main__":
    main()
