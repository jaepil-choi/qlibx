"""
SHFE File Day Data Extractor
============================

Extracts daily OHLCV data from SHFE (Shanghai Futures Exchange) raw files.
"""
import pandas as pd
import glob
import os
import logging
from pathlib import Path
from typing import Optional, ClassVar, Set

from ..base import BaseExtractor
from echolon.config.markets.factory import MarketFactory

logger = logging.getLogger(__name__)


class SHFEFileDayExtractor(BaseExtractor):
    """
    Extractor for SHFE daily futures data from raw files.

    Handles extraction from raw Excel files provided by the exchange.

    Capabilities:
    - batch: extract all data from source files
    - calendar_generate: derives trading calendar from extracted data
    """

    capabilities: ClassVar[Set[str]] = {"batch", "calendar_generate"}

    # Chinese to English column mapping
    COLUMN_MAPPING = {
        '合约': 'contract',
        '日期': 'date',
        '前收盘': 'prev_close',
        '前结算': 'prev_settlement',
        '开盘价': 'open',
        '最高价': 'high',
        '最低价': 'low',
        '收盘价': 'close',
        '结算价': 'settlement',
        '涨跌1': 'price_change',
        '涨跌2': 'settlement_change',
        '成交量': 'volume',
        '成交金额': 'turnover',
        '持仓量': 'open_interest',
        '交易日期': 'date',
        '成交金额(万元)': 'turnover',
    }

    def __init__(
        self,
        market: str,
        asset: str,
        raw_data_dir: Optional[Path] = None,
    ):
        super().__init__(market, asset)
        self.futures_code = self._get_futures_code(asset)
        if raw_data_dir is None:
            from echolon.config.paths_config import PathsConfig
            raw_data_dir = PathsConfig.from_env().raw_data_dir
        self._raw_data_dir = Path(raw_data_dir)

    def _get_futures_code(self, asset: str) -> str:
        """Get the futures code for an asset name using MarketFactory."""
        instrument_spec = MarketFactory.get_instrument_flexible(self.market, asset)
        if not instrument_spec:
            supported = MarketFactory.list_instruments(self.market)
            raise ValueError(f"Unknown asset: {asset}. Supported: {supported}")
        return instrument_spec.code

    def _get_default_paths(self) -> dict:
        """Get default input/output paths based on market and asset.

        Input paths default to the constructor-supplied ``raw_data_dir`` (or
        the lazy fallback derived from ``PathsConfig.from_env()``); output_dir must be
        supplied explicitly to extract_raw — echolon no longer writes to the
        package install directory by default.

        The day-data subdir is named ``day_data`` (parallel to the
        per-instrument ``minute_data/`` directory used by
        SHFEApiMinuteExtractor). i.e. the canonical raw-data tree is::

            {raw_data_dir}/SHFE/
              day_data/         # multi-instrument multi-year xls (this extractor's input)
              {al,cu,zn,...}/
                minute_data/    # per-instrument minute OHLCV (the api_minute_extractor's per-contract output)
        """
        market_dir = os.path.join(str(self._raw_data_dir), self.market)
        return {
            "raw_data": os.path.join(market_dir, "day_data"),
        }

    def extract_raw(
        self,
        input_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save: bool = True
    ) -> pd.DataFrame:
        """
        Extract futures data from raw SHFE Excel files.

        Args:
            input_dir: Directory containing raw Excel files.
                       Defaults to {raw_data_dir}/{market}/day_data when not provided.
            output_dir: Directory to save extracted CSV. Required when save=True.
            start_date: Optional start date filter
            end_date: Optional end date filter
            save: Whether to save the extracted data to CSV (default True)

        Raises:
            ValueError: if save=True and output_dir is not provided.

        Returns:
            DataFrame with extracted OHLCV data
        """
        if save and output_dir is None:
            raise ValueError(
                "output_dir is required for extraction. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default. "
                "Typical convention: MARKET_DATA_DIR / market / instrument"
            )

        paths = self._get_default_paths()
        input_dir = input_dir or paths["raw_data"]

        if save:
            os.makedirs(output_dir, exist_ok=True)

        # Get all Excel files
        excel_files = glob.glob(os.path.join(input_dir, "*.xls*"))

        if not excel_files:
            logger.warning(f"[SHFE_EXTRACTOR] No Excel files found in {input_dir}")
            return pd.DataFrame()

        logger.info(f"[SHFE_EXTRACTOR] Processing {len(excel_files)} files")

        all_data = []

        for file_path in excel_files:
            df = pd.read_excel(file_path, header=2)

            # Map columns
            df = df.rename(columns={k: v for k, v in self.COLUMN_MAPPING.items() if k in df.columns})

            # Forward fill contract column
            if 'contract' in df.columns:
                df['contract'] = df['contract'].ffill()
            else:
                df.iloc[:, 0] = df.iloc[:, 0].ffill()

            # Filter for this futures type
            contract_col = 'contract' if 'contract' in df.columns else df.columns[0]
            futures_data = df[
                (df[contract_col].astype(str).str.startswith(self.futures_code, na=False)) &
                (df[contract_col].astype(str).str.len() == 6)
            ]

            if not futures_data.empty:
                # Drop rows with NaN dates (from summary/trailing rows in Excel)
                if 'date' in futures_data.columns:
                    futures_data = futures_data.dropna(subset=['date'])
                all_data.append(futures_data)

        if not all_data:
            logger.warning(f"[SHFE_EXTRACTOR] No {self.asset} data found")
            return pd.DataFrame()

        # Combine all data
        result = pd.concat(all_data, ignore_index=True)

        # Ensure date is numeric for sorting
        if 'date' in result.columns:
            result['date'] = pd.to_numeric(result['date'], errors='coerce').astype('Int64')

        # Sort by date and contract
        contract_col = 'contract' if 'contract' in result.columns else result.columns[0]
        result = result.sort_values(by=['date', contract_col])

        # Save to CSV if requested
        if save and output_dir:
            output_file = os.path.join(output_dir, 'sort_by_date.csv')
            result.to_csv(output_file, index=False)
            logger.info(f"[SHFE_EXTRACTOR] Extracted {len(result)} rows to {output_file}")
        else:
            logger.info(f"[SHFE_EXTRACTOR] Extracted {len(result)} rows (not saved)")

        return result

    # Note: split_by_contract and generate_trading_calendar are inherited
    # from BaseExtractor, which delegates to transformer classes.
