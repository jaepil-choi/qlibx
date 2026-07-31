"""SHFE daily-data extractor via akshare (Sina Finance mirror).

Free, no registry, no token. Optional dep — `pip install echolon[shfe]`.

Schema mapping:
    akshare    → canonical
    -----------------------
    date       → date  (YYYY-MM-DD strings)
    open/high/low/close → as-is
    volume     → volume
    hold       → open_interest

Synthesized when akshare doesn't expose them:
    settlement       = settle when present, otherwise close
    prev_close       = close.shift(1) per contract
    prev_settlement  = settlement.shift(1)
    price_change     = close - prev_close
    settlement_change= settlement - prev_settlement
    turnover         = volume * close
"""
from __future__ import annotations
from pathlib import Path
from typing import ClassVar, List, Optional, Set
import logging
import os

import pandas as pd

from ..base import BaseExtractor
from echolon.config.markets.factory import MarketFactory

logger = logging.getLogger(__name__)


class SHFEAkshareExtractor(BaseExtractor):
    """Extractor for SHFE daily OHLCV via akshare (Sina mirror)."""

    capabilities: ClassVar[Set[str]] = {"batch", "calendar_generate", "online"}

    CANONICAL_COLUMNS: ClassVar[list[str]] = [
        "contract", "date",
        "prev_close", "prev_settlement",
        "open", "high", "low", "close",
        "settlement",
        "price_change", "settlement_change",
        "volume", "turnover", "open_interest",
    ]

    def __init__(self, market: str, asset: str):
        super().__init__(market, asset)
        spec = MarketFactory.get_instrument_flexible(market, asset)
        if spec is None:
            raise ValueError(
                f"Unknown asset: {asset}. Supported: "
                f"{MarketFactory.list_instruments(market)}"
            )
        self.futures_code = spec.code

    def _list_contracts_in_range(self, start_date: str, end_date: str) -> List[str]:
        """Enumerate plausible contract codes in YYMM convention.

        Over-emits; downloader skips contracts with no data. v2 could
        query akshare's contract-listing endpoint instead.
        """
        start = pd.to_datetime(start_date) - pd.DateOffset(months=2)
        end = pd.to_datetime(end_date) + pd.DateOffset(months=15)
        codes: list[str] = []
        cursor = start
        while cursor <= end:
            codes.append(f"{self.futures_code}{cursor.year % 100:02d}{cursor.month:02d}")
            cursor = cursor + pd.DateOffset(months=1)
        return codes

    def extract_raw(
        self,
        input_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save: bool = True,
    ) -> pd.DataFrame:
        if start_date is None or end_date is None:
            raise ValueError("start_date and end_date are required")
        if save and output_dir is None:
            raise ValueError("output_dir required when save=True")

        try:
            import akshare as ak
        except ImportError as e:
            raise ImportError(
                "akshare required for SHFEAkshareExtractor. "
                "Install with `pip install echolon[shfe]`."
            ) from e

        all_frames: list[pd.DataFrame] = []
        for contract in self._list_contracts_in_range(start_date, end_date):
            logger.info(f"[SHFE_AKSHARE] Fetching {contract.upper()}")
            try:
                df = ak.futures_zh_daily_sina(symbol=contract.upper())
            except (ValueError, KeyError, AttributeError) as e:
                logger.debug(f"[SHFE_AKSHARE] Skipping {contract}: {type(e).__name__}: {e}")
                continue
            if df is None or len(df) == 0:
                continue
            try:
                df = df.copy()
                df["contract"] = contract
                df = df.rename(columns={"hold": "open_interest"})
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df[df["date"] <= end_date]
                if df.empty:
                    continue
                df = df.sort_values("date").reset_index(drop=True)
                df["prev_close"] = df["close"].shift(1).fillna(df["close"])
                if "settle" in df.columns:
                    df["settlement"] = df["settle"].fillna(df["close"])
                else:
                    df["settlement"] = df["close"]
                df["prev_settlement"] = df["settlement"].shift(1).fillna(df["settlement"])
                df["price_change"] = df["close"] - df["prev_close"]
                df["settlement_change"] = df["settlement"] - df["prev_settlement"]
                df["turnover"] = df["volume"] * df["close"]
                all_frames.append(df[self.CANONICAL_COLUMNS])
            except (ValueError, KeyError) as e:
                logger.debug(f"[SHFE_AKSHARE] Skipping {contract} during shape: {e}")
                continue

        if not all_frames:
            logger.warning(f"[SHFE_AKSHARE] No data for {self.futures_code} in [{start_date}, {end_date}]")
            return pd.DataFrame(columns=self.CANONICAL_COLUMNS)

        combined = pd.concat(all_frames, ignore_index=True)
        combined = combined.sort_values(["contract", "date"]).reset_index(drop=True)
        if save:
            os.makedirs(output_dir, exist_ok=True)
            combined.to_csv(Path(output_dir) / "raw_data.csv", index=False)
        return combined
