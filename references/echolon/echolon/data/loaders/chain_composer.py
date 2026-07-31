"""
Chain Composer (futures forward-curve assembly)
================================================

Multi-contract composition primitives for futures markets, used by carry
paradigm sleeves to construct a same-date forward-curve snapshot across
the active contract chain.

Public API:
- ``get_contract_chain(symbol, trading_date, *, market_data_dir,
  n_contracts=None) -> list[str]``
- ``get_curve_snapshot(symbol, trading_date, *, market_data_dir,
  n_contracts=None) -> pd.DataFrame``

Design (per Gate 1C WS2 B2.1, qorka 2026-05-14 + verification spike
2026-05-14):

* "Active on date" = (a) ``expiry_date >= trading_date`` AND (b) per-
  contract OHLCV has a row for ``trading_date``. Without (b) we'd return
  delisted-but-not-yet-expired contracts with no settlement data; without
  (a) we'd miss the canonical SHFE "must close by last trading day of
  month before delivery" rule. Both checks together = tradeable.

* Settlement column lives in the per-contract OHLCV row (Q1c / Q50
  spike) — NOT in ContractSpec metadata. Settlement is time-varying;
  caching it on the metadata object would be a category error.

* No try/except: ``raise_error`` from the echolon error catalog
  propagates fail-loud per qorka NO_ERROR_HANDLING policy.

The composer routes through ``ohlcv_loader.get_available_contracts`` +
``load_contract_ohlcv`` (NOT ``ContractIndicatorManager`` — that reads
the post-indicator-compute layout under ``by_contract/``, which lacks
the raw OHLCV ``settlement`` column).
"""
from __future__ import annotations

import logging
from datetime import date as _date
from pathlib import Path
from typing import List, Optional

import pandas as pd

from echolon.config.markets.factory import MarketFactory
from echolon.data.loaders.ohlcv_loader import (
    get_available_contracts,
    load_contract_ohlcv,
)
from echolon.errors import raise_error
from echolon.markets.shfe.contract_rules import get_expiry_date, parse_contract

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_asset_name(market: str, symbol: str) -> str:
    """Resolve a product code or full asset name to the canonical instrument name.

    The per-contract loader uses the instrument's canonical name
    (e.g., ``aluminum``) in the path, not the code (``al``). This shim
    lets callers pass either form.
    """
    spec = MarketFactory.get_instrument_flexible(market.upper(), symbol.lower())
    if spec is None:
        raise_error("DAT-003", path=f"<unknown-instrument:{symbol}>", symbol=symbol)
    return spec.name.lower()


def _has_row_for_date(df: Optional[pd.DataFrame], target_date: _date) -> bool:
    """True iff `df` has at least one row whose `date` column equals
    `target_date`.

    Per-contract files have a `date` column (datetime64[ns]) per
    ``ohlcv_loader._ensure_datetime_types``; we compare the date-part.
    """
    if df is None or df.empty or "date" not in df.columns:
        return False
    matched = df[df["date"].dt.date == target_date]
    return len(matched) > 0


def _row_for_date(df: pd.DataFrame, target_date: _date) -> pd.Series:
    """Return the OHLCV row matching `target_date`. Assumes existence."""
    matched = df[df["date"].dt.date == target_date]
    return matched.iloc[0]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_contract_chain(
    symbol: str,
    trading_date: _date,
    *,
    market: str = "SHFE",
    market_data_dir: Path,
    n_contracts: Optional[int] = None,
) -> List[str]:
    """Enumerate active contracts for ``symbol`` on ``trading_date``.

    "Active" means both:
      (a) Contract's expiry (per SHFE rule = last trading day of month
          BEFORE the delivery month) is on or after ``trading_date``.
      (b) Per-contract OHLCV (``sort_by_contract/{contract}.csv``) has
          a row for ``trading_date``.

    Args:
        symbol: Product code (e.g., ``'al'``, ``'zn'``) OR full
            instrument name (e.g., ``'aluminum'``, ``'zinc'``).
        trading_date: Date to enumerate the chain for.
        market: Market code. Defaults to ``'SHFE'`` (the only market
            with multi-contract forward curves in Gate 1C scope).
        market_data_dir: Required base market-data directory (typically
            ``paths.market_data_dir``). Forwarded to ``ohlcv_loader``.
        n_contracts: If given, truncate to the nearest-expiry
            ``n_contracts``. None returns the full active chain.

    Returns:
        List of contract codes (e.g., ``['zn2406', 'zn2407', 'zn2408']``)
        sorted by expiry ascending — front contract first.

    Raises:
        EchelonError DAT-003: if the symbol does not resolve to a known
            instrument or if ``sort_by_contract/`` is missing.
        Any error raised by ``ohlcv_loader.load_contract_ohlcv``.
    """
    asset_name = _resolve_asset_name(market, symbol)
    all_contracts = get_available_contracts(
        market=market.upper(),
        asset=asset_name,
        market_data_dir=market_data_dir,
    )

    if not all_contracts:
        # No per-contract files at all — surface this as DAT-003 so the
        # caller learns the chain dir is missing, rather than getting a
        # silent empty list.
        raise_error(
            "DAT-003",
            path=str(
                Path(market_data_dir)
                / market.upper()
                / asset_name
                / "sort_by_contract"
            ),
            symbol=symbol,
        )

    # Per-instrument trading calendar: passing None to get_expiry_date
    # uses the simple "last day of month minus weekends" approximation,
    # which is fine for chain ordering (we only need monotone-correct
    # ordering, not exact SHFE holiday-aware expiry).
    active: List[tuple[_date, str]] = []
    for contract in all_contracts:
        # Skip contracts whose code is malformed for this product
        product_code, _, _ = parse_contract(contract)
        if product_code != _resolve_product_code(market, symbol):
            continue

        expiry = get_expiry_date(contract, calendar=None)
        if expiry < trading_date:
            continue

        df = load_contract_ohlcv(
            market=market.upper(),
            asset=asset_name,
            contract=contract,
            market_data_dir=market_data_dir,
        )
        if not _has_row_for_date(df, trading_date):
            continue

        active.append((expiry, contract))

    active.sort(key=lambda x: x[0])
    chain = [c for (_, c) in active]
    if n_contracts is not None:
        chain = chain[:n_contracts]

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "[CHAIN_COMPOSER] %s %s → %d active contracts: %s",
            symbol, trading_date, len(chain), chain,
        )
    return chain


def _resolve_product_code(market: str, symbol: str) -> str:
    """Inverse of `_resolve_asset_name`: returns the 2-letter product code."""
    spec = MarketFactory.get_instrument_flexible(market.upper(), symbol.lower())
    if spec is None:
        raise_error("DAT-003", path=f"<unknown-instrument:{symbol}>", symbol=symbol)
    return spec.code.lower()


def get_curve_snapshot(
    symbol: str,
    trading_date: _date,
    *,
    market: str = "SHFE",
    market_data_dir: Path,
    n_contracts: Optional[int] = None,
) -> pd.DataFrame:
    """Build a same-date forward-curve snapshot across the active chain.

    Returns one row per active contract with these columns (subset of
    canonical OHLCV+futures schema, per ``echolon.data.schemas``):

      - ``contract``       — contract code (``'zn2406'`` etc.)
      - ``date``           — trading_date (datetime64[ns] from the OHLCV)
      - ``open``, ``high``, ``low``, ``close``, ``volume``  — usual OHLCV
      - ``settlement``     — settlement price (float64) — load-bearing
                              for carry indicators (Q50 spike)
      - ``open_interest``  — when present in the per-contract file
      - ``expiry_date``    — datetime64-of-date, computed via
                              ``contract_rules.get_expiry_date``
      - ``days_to_expiry`` — integer day count (``expiry - trading_date``)

    Rows are sorted by ``expiry_date`` ascending; the first row is the
    front contract.

    Args:
        symbol: Product code or instrument name.
        trading_date: Date to snapshot the curve for.
        market: Market code (default ``'SHFE'``).
        market_data_dir: Required base market-data directory.
        n_contracts: If given, truncate to the nearest-expiry
            ``n_contracts``.

    Returns:
        DataFrame with one row per active contract. May be EMPTY if no
        contracts are active for the date (caller decides whether to
        treat empty curves as a hard error vs. skip-day).
    """
    asset_name = _resolve_asset_name(market, symbol)
    chain = get_contract_chain(
        symbol,
        trading_date,
        market=market,
        market_data_dir=market_data_dir,
        n_contracts=n_contracts,
    )

    rows: List[dict] = []
    for contract in chain:
        df = load_contract_ohlcv(
            market=market.upper(),
            asset=asset_name,
            contract=contract,
            market_data_dir=market_data_dir,
        )
        # _has_row_for_date already returned True for this contract in
        # get_contract_chain, but a defensive re-check keeps the function
        # callable in isolation (someone may pass a hand-curated chain).
        if not _has_row_for_date(df, trading_date):
            continue
        row = _row_for_date(df, trading_date)
        expiry = get_expiry_date(contract, calendar=None)
        rec = {
            "contract": contract,
            "date": row["date"] if "date" in row.index else None,
            "expiry_date": pd.Timestamp(expiry),
            "days_to_expiry": (expiry - trading_date).days,
        }
        # Pull whichever OHLCV/settlement/OI columns are present
        for col in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "settlement",
            "open_interest",
            "turnover",
        ):
            if col in row.index:
                rec[col] = row[col]
        rows.append(rec)

    if not rows:
        # Empty DataFrame with the canonical column set so downstream
        # code can rely on column names existing.
        return pd.DataFrame(
            columns=[
                "contract",
                "date",
                "expiry_date",
                "days_to_expiry",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "settlement",
                "open_interest",
            ]
        )

    snapshot = pd.DataFrame(rows)
    # Already sorted by chain (which sorts by expiry), but force the
    # contract ordering explicitly so callers can rely on iloc[0] = front.
    snapshot = snapshot.sort_values("expiry_date").reset_index(drop=True)
    return snapshot
