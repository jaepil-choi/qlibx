"""
SHFE API Day Data Extractor
============================

Extracts daily OHLCV data from SHFE via MiniQMT API.

This extractor connects to a MiniQMT client to download per-contract
daily OHLCV data for SHFE futures.  It provides both full extraction
(``extract_raw``) and incremental update (``update_incremental``)
capabilities.

Output format:
    CSV columns: contract, date (YYYYMMDD int), open, high, low, close, volume
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, ClassVar

import pandas as pd

from ..base import BaseExtractor
from echolon.config.markets.factory import MarketFactory

logger = logging.getLogger(__name__)


class SHFEApiDayExtractor(BaseExtractor):
    """
    Extractor for SHFE daily futures data via MiniQMT API.

    Downloads per-contract OHLCV data from a connected MiniQMT client.
    Supports both full extraction and incremental updates.

    Args:
        market: Market code (e.g., ``"SHFE"``)
        asset: Asset name (e.g., ``"aluminum"``)
        client: Optional MiniQMT client instance (can be set later via
            :meth:`set_client`)
        present_date: Reference "now" date for the pipeline run

    Capabilities:
    - batch: extract all daily data from source
    - incremental: download only new bars since last extraction
    - calendar_load: loads a pre-built trading calendar (not generated from data)
    - main_contract: produce aggregated main contract from per-contract data
    """

    capabilities: ClassVar[Set[str]] = {
        "batch",
        "incremental",
        "calendar_load",
        "main_contract",
    }

    def __init__(
        self,
        market: str,
        asset: str,
        client=None,
        present_date: Optional[datetime] = None,
    ):
        super().__init__(market, asset)
        self.futures_code = self._get_futures_code(asset)
        self.xuntou_code = self._get_xuntou_code(market)
        self.client = client
        self.present_date = present_date or datetime.now()
        self.valid_contracts: Set[str] = set()

    def _get_futures_code(self, asset: str) -> str:
        """Get the futures code for an asset name using MarketFactory."""
        instrument_spec = MarketFactory.get_instrument_flexible(self.market, asset)
        if not instrument_spec:
            supported = MarketFactory.list_instruments(self.market)
            raise ValueError(f"Unknown asset: {asset}. Supported: {supported}")
        return instrument_spec.code

    def _get_xuntou_code(self, market: str) -> str:
        """Get the xuntou market code from MarketConfig."""
        market_config = MarketFactory.get_market_config(market)
        if not market_config:
            raise ValueError(f"Unknown market: {market}")
        return market_config.xuntou_code

    def set_client(self, client) -> None:
        """Set or replace the MiniQMT client for API calls."""
        self.client = client

    def _require_client(self) -> None:
        """Raise ``RuntimeError`` if client is not set."""
        if self.client is None:
            raise RuntimeError(
                "Data client required but not set. "
                "Pass client (XtdcClient or MiniQMTClient) to constructor "
                "or call set_client() first."
            )

    # ------------------------------------------------------------------
    # extract_raw  (BaseExtractor entry point)
    # ------------------------------------------------------------------

    def extract_raw(
        self,
        input_dir: Optional[str] = None,  # noqa: ARG002 - Not used for API extraction
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save: bool = True,
    ) -> pd.DataFrame:
        """
        Extract daily OHLCV data for all valid contracts from MiniQMT.

        Discovers valid contracts, downloads full history for each,
        and optionally saves per-contract CSVs.

        Args:
            input_dir: Not used for API extraction
            output_dir: Directory to save per-contract CSVs
            start_date: Optional start date (YYYYMMDD)
            end_date: Optional end date (YYYYMMDD)
            save: Whether to save per-contract CSVs (default True)

        Returns:
            Combined DataFrame with all contracts' OHLCV data
        """
        _ = input_dir  # Not used for API extraction

        if save and output_dir is None:
            raise ValueError(
                "output_dir is required for extraction. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default. "
                "Typical convention: MARKET_DATA_DIR / market / instrument / futures_code_by_contract"
            )

        self._require_client()

        # Extract main contract — save to the same output_dir parent
        main_contract_dir = output_dir if output_dir else None
        self.extract_main_contract(output_dir=main_contract_dir)

        contracts = self._discover_contracts()
        if not contracts:
            logger.error("[SHFE_LIVE_DAY] No valid contracts found")
            return pd.DataFrame()

        all_frames: List[pd.DataFrame] = []
        for contract in contracts:
            logger.info(f"[SHFE_LIVE_DAY] Downloading {contract}")
            df = self._download_single_contract(
                contract, start_date=start_date, end_date=end_date,
            )
            if df is not None and not df.empty:
                all_frames.append(df)
            time.sleep(1)

        if not all_frames:
            logger.error("[SHFE_LIVE_DAY] No data downloaded for any contract")
            return pd.DataFrame()

        combined = pd.concat(all_frames, ignore_index=True)
        logger.info(
            f"[SHFE_LIVE_DAY] Downloaded {len(combined)} total rows "
            f"across {len(all_frames)} contracts"
        )

        if save and output_dir:
            os.makedirs(output_dir, exist_ok=True)
            for contract_name, group in combined.groupby('contract'):
                file_path = os.path.join(output_dir, f"{contract_name}.csv")
                group.to_csv(file_path, index=False)
            logger.info(
                f"[SHFE_LIVE_DAY] Saved per-contract CSVs to {output_dir}"
            )

        return combined

    # ------------------------------------------------------------------
    # Incremental update  (deploy-specific workflow)
    # ------------------------------------------------------------------

    def update_incremental(self, output_dir: str) -> pd.DataFrame:
        """
        Incrementally update per-contract CSVs with new bars only.

        For each valid contract, loads existing CSV (if any), downloads
        data up to the present trading date, and appends only new rows.

        Args:
            output_dir: Directory containing per-contract CSVs

        Returns:
            Combined DataFrame with all contracts' updated data
        """
        self._require_client()
        os.makedirs(output_dir, exist_ok=True)

        contracts = self._discover_contracts()
        if not contracts:
            logger.error("[SHFE_LIVE_DAY] No valid contracts found")
            return pd.DataFrame()

        results: Dict[str, bool] = {}
        for contract in contracts:
            logger.info(f"[SHFE_LIVE_DAY] Incrementally updating {contract}")
            success = self._update_single_contract(contract, output_dir)
            results[contract] = success
            time.sleep(1)

        success_count = sum(v for v in results.values())
        logger.info(
            f"[SHFE_LIVE_DAY] Updated {success_count}/{len(contracts)} contracts"
        )

        # Load and return combined data
        all_frames: List[pd.DataFrame] = []
        for contract in contracts:
            contract_base = contract.split('.')[0]
            file_path = os.path.join(output_dir, f"{contract_base}.csv")
            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                if not df.empty:
                    all_frames.append(df)

        if not all_frames:
            return pd.DataFrame()

        return pd.concat(all_frames, ignore_index=True)

    # ------------------------------------------------------------------
    # Main contract
    # ------------------------------------------------------------------
    def extract_main_contract(self, output_dir: Optional[str] = None):
        """Download main contract history via client.

        Requires a client with ``download_main_contract_history()``
        (e.g. XtdcClient for token-based API, or MiniQMTClient).
        The client manages the xtdata connection lifecycle externally,
        so no per-call connect/disconnect happens here.

        Args:
            output_dir: Directory to save main contract data. Required when
                        a client that saves data is in use. Callers must supply
                        this explicitly — echolon no longer defaults to the
                        package install directory.
        """
        self._require_client()

        if not hasattr(self.client, 'download_main_contract_history'):
            logger.error(
                "Client %s does not support download_main_contract_history",
                type(self.client).__name__,
            )
            return None

        logger.info(f"Futures code: {self.futures_code}")
        logger.info(f"xuntou code: {self.xuntou_code}")

        df = self.client.download_main_contract_history(
            futures_code=self.futures_code,
            xuntou_code=self.xuntou_code,
            output_dir=output_dir,
        )

        if df is None or df.empty:
            logger.error("Failed to extract main contract data")
            return None

        logger.info(f"Extracted {len(df)} main contract entries")
        logger.info(f"Date range: {df['date'].min()} to {df['date'].max()}")


    # ------------------------------------------------------------------
    # Trading calendar
    # ------------------------------------------------------------------

    def generate_trading_calendar(
        self,
        source_path: str,                       # required
        output_dir: Optional[str] = None,
        data: pd.DataFrame = None,              # unused; base-class compat
        start_date: Optional[str] = None,       # unused; base-class compat
    ) -> pd.DataFrame:
        """Load a pre-computed SHFE trading calendar and optionally copy to output_dir.

        SHFE does not publish a machine-readable trading-calendar API, so callers
        MUST derive one from the official holiday schedule at shfe.com.cn and pass
        its path here.

        Expected CSV schema:
            date            YYYY-MM-DD
            is_trading_day  bool
            night_market    bool    (whether the night session is open that day)

        Args:
            source_path: Path to a pre-computed trading_calendar.csv. Required.
            output_dir:  Optional — when set, a copy is written to
                         ``{output_dir}/trading_calendar.csv`` (for per-slot deploy dirs).

        Raises:
            ValueError: if source_path is empty or missing.
        """
        _ = data, start_date

        if not source_path:
            raise ValueError(
                "SHFEApiDayExtractor.generate_trading_calendar requires an explicit "
                "source_path. SHFE has no public trading-calendar API — derive one from "
                "the official holiday schedule at shfe.com.cn and ship the CSV alongside "
                "your deploy configuration (e.g. session/trading_calendar.csv), then "
                "pass source_path=<that path>."
            )

        calendar_df = pd.read_csv(source_path)
        logger.info(
            f"[SHFE_LIVE_DAY] Loaded trading calendar ({len(calendar_df)} rows) from {source_path}"
        )

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, 'trading_calendar.csv')
            calendar_df.to_csv(out_path, index=False)
            logger.info(f"[SHFE_LIVE_DAY] Saved trading calendar to {out_path}")

        return calendar_df

    # ------------------------------------------------------------------
    # Contract discovery
    # ------------------------------------------------------------------

    def _discover_contracts(self) -> List[str]:
        """
        Retrieve currently valid contracts from SHFE via client.

        Returns:
            Sorted list of full contract codes
            (e.g. ``['al2507.SF', ...]``).
        """
        self._require_client()

        logger.info(
            f"[SHFE_LIVE_DAY] Discovering valid {self.futures_code} "
            f"contracts from SHFE"
        )
        all_shfe_contracts = self.client.get_stock_list_in_sector(
            self.xuntou_code,
        )

        if not all_shfe_contracts:
            logger.error(
                "[SHFE_LIVE_DAY] Failed to get SHFE contract list"
            )
            return []

        logger.info(
            f"[SHFE_LIVE_DAY] Retrieved {len(all_shfe_contracts)} "
            f"total SHFE contracts"
        )

        pattern = re.compile(
            rf'^{self.futures_code}\d{{4}}\.{self.xuntou_code}$',
            re.IGNORECASE,
        )
        valid = [
            c for c in all_shfe_contracts if pattern.match(c)
        ]

        if not valid:
            logger.error(
                f"[SHFE_LIVE_DAY] No {self.futures_code} contracts found"
            )
            return []

        code_len = len(self.futures_code)
        valid.sort(key=lambda x: x[code_len:code_len + 4])
        self.valid_contracts = set(valid)
        logger.info(
            f"[SHFE_LIVE_DAY] Found {len(valid)} valid contracts: "
            f"{valid}"
        )
        return valid

    # ------------------------------------------------------------------
    # Data download
    # ------------------------------------------------------------------

    def _download_single_contract(
        self,
        contract: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Download OHLCV data for a single contract from MiniQMT.

        Args:
            contract: Full contract code (e.g. ``'al2507.SF'``)
            start_date: Optional start date (YYYYMMDD)
            end_date: Optional end date (YYYYMMDD)

        Returns:
            DataFrame in pipeline format or ``None`` on failure
        """
        self._require_client()
        logger.info(f"[SHFE_LIVE_DAY] Downloading data for {contract}")

        market_data = self.client.get_market_data(
            symbols=[contract],
            period='1d',
            start_time='',
            end_time=end_date,
        )

        if not market_data:
            logger.error(
                f"[SHFE_LIVE_DAY] No market data retrieved for {contract}"
            )
            return None

        qts_df = self.client.extract_dataframe_from_data(
            market_data, contract,
        )

        if qts_df is None or qts_df.empty:
            logger.error(
                f"[SHFE_LIVE_DAY] Failed to extract DataFrame for {contract}"
            )
            return None

        formatted = self._convert_to_pipeline_format(qts_df, contract)
        logger.info(
            f"[SHFE_LIVE_DAY] Retrieved {len(formatted)} rows for {contract}"
        )
        return formatted

    @staticmethod
    def _convert_to_pipeline_format(
        df: pd.DataFrame, contract: str,
    ) -> pd.DataFrame:
        """
        Convert a raw client DataFrame into standard pipeline CSV format.

        Columns: contract, date (YYYYMMDD int), open, high, low, close,
        volume
        """
        if df.empty:
            return pd.DataFrame()

        contract_base = contract.split('.')[0]

        result = pd.DataFrame({
            'contract': [contract_base] * len(df),
            'date': df.index.strftime('%Y%m%d').astype(int),
            'open': df['open'].astype(float),
            'high': df['high'].astype(float),
            'low': df['low'].astype(float),
            'close': df['close'].astype(float),
            'volume': df['volume'].astype(float),
        })

        return result.dropna().reset_index(drop=True)

    # ------------------------------------------------------------------
    # Incremental update helpers
    # ------------------------------------------------------------------

    def _get_present_trading_date(self) -> str:
        """
        Resolve the present trading date from the calendar.

        If *present_date* is in the calendar it is returned directly;
        otherwise the next future trading date is used.  Falls back to
        *present_date* formatted as YYYYMMDD.
        """
        present_str = self.present_date.strftime('%Y%m%d')

        try:
            from echolon.data.loaders.calendar_loader import (
                load_trading_calendar,
            )
            calendar_df = load_trading_calendar(self.market, self.asset)
            trading_dates = (
                calendar_df['date'].dt.strftime('%Y%m%d').tolist()
            )
        except Exception:
            logger.warning(
                "[SHFE_LIVE_DAY] Trading calendar not available, "
                "using present_date"
            )
            return present_str

        if not trading_dates:
            return present_str

        if present_str in trading_dates:
            return present_str

        future = [d for d in trading_dates if d > present_str]
        if future:
            return min(future)

        return present_str

    def _update_single_contract(
        self, contract: str, output_dir: str,
    ) -> bool:
        """
        Incrementally update the local CSV for a single contract.

        New bars are appended; duplicates are removed.

        Args:
            contract: Full contract code (e.g. ``'al2507.SF'``)
            output_dir: Directory containing per-contract CSVs

        Returns:
            ``True`` on success (including "no new data")
        """
        contract_base = contract.split('.')[0]
        file_path = os.path.join(output_dir, f"{contract_base}.csv")

        last_trading_date = self._get_present_trading_date()

        downloaded = self._download_single_contract(
            contract, start_date="", end_date=last_trading_date,
        )
        if downloaded is None or downloaded.empty:
            logger.error(
                f"[SHFE_LIVE_DAY] Failed to download data for {contract}"
            )
            return False

        if os.path.exists(file_path):
            existing_df = pd.read_csv(file_path)
            if not existing_df.empty:
                latest_existing_date = existing_df['date'].max()
                new_data = downloaded[
                    downloaded['date'] > latest_existing_date
                ]

                if new_data.empty:
                    logger.info(
                        f"[SHFE_LIVE_DAY] No new data for {contract}"
                    )
                    return True

                combined_df = pd.concat(
                    [existing_df, new_data], ignore_index=True,
                )
                combined_df = (
                    combined_df
                    .drop_duplicates(subset=['date'], keep='last')
                    .sort_values('date')
                    .reset_index(drop=True)
                )
                logger.info(
                    f"[SHFE_LIVE_DAY] Added {len(new_data)} new rows "
                    f"to {contract}"
                )
            else:
                combined_df = downloaded
        else:
            combined_df = downloaded
            logger.info(
                f"[SHFE_LIVE_DAY] Created new file for {contract} "
                f"with {len(downloaded)} rows"
            )

        combined_df.to_csv(file_path, index=False)
        return True

    # ------------------------------------------------------------------
    # Validation & utilities
    # ------------------------------------------------------------------

    def validate_data_format(self, file_path: str) -> bool:
        """
        Check that a CSV file contains the expected columns.

        Expected: contract, date, open, high, low, close, volume
        """
        expected = [
            'contract', 'date', 'open', 'high', 'low', 'close', 'volume',
        ]
        df = pd.read_csv(file_path, nrows=1)
        missing = [c for c in expected if c not in df.columns]
        if missing:
            logger.error(
                f"[SHFE_LIVE_DAY] Missing columns in {file_path}: {missing}"
            )
            return False
        return True

    def get_available_local_contracts(self, data_dir: str) -> List[str]:
        """
        Return sorted list of contracts with local CSV files.

        Args:
            data_dir: Directory containing per-contract CSVs

        Returns:
            Sorted list of contract base names
        """
        contracts = []
        if os.path.exists(data_dir):
            for f in os.listdir(data_dir):
                if f.endswith('.csv') and f.startswith(self.futures_code):
                    contracts.append(f.replace('.csv', ''))
        return sorted(contracts)
