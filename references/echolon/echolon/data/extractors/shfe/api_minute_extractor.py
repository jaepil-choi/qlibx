"""
SHFE API Minute Data Extractor
==============================

Extracts minute-level OHLCV data from SHFE via xuntou (迅投) API.

Requires a data client with an active xtdata connection (e.g. XtdcClient)
passed via set_client() or the constructor. The client manages the
connection lifecycle; this extractor only calls data methods on it.

Note: Requires xtquant library and valid API credentials.
"""
import logging
from typing import Optional, List, ClassVar, Set
from pathlib import Path
import pandas as pd

from ..base import BaseExtractor
from echolon.config.markets.factory import MarketFactory

logger = logging.getLogger(__name__)


# Market code mapping for xuntou API
XUNTOU_MARKET_CODES = {
    "SHFE": "SF",    # Shanghai Futures Exchange
    "DCE": "DF",     # Dalian Commodity Exchange
    "CZCE": "ZF",    # Zhengzhou Commodity Exchange
    "CFFEX": "IF",   # China Financial Futures Exchange
}


class SHFEApiMinuteExtractor(BaseExtractor):
    """
    Extractor for SHFE minute-level futures data via xuntou API.

    This extractor:
    1. Downloads main contract history
    2. Downloads minute OHLCV data for each contract
    3. Saves data in standardized format

    Requires a client (e.g. XtdcClient) that provides:
    - download_main_contract_history(futures_code, xuntou_code, output_dir)
    - download_history_data(symbols, period, ...)
    - get_market_data(symbols, period, ...) (optional, for minute downloads)

    The client is injected via set_client() — called automatically by
    run_data_pipeline() when a client is provided.

    Capabilities:
    - batch: extract all minute data from source
    - calendar_generate: derives trading calendar from extracted data
    - main_contract: produce aggregated main contract from per-contract data
    """

    capabilities: ClassVar[Set[str]] = {
        "batch",
        "calendar_generate",
        "main_contract",
    }

    def __init__(
        self,
        market: str,
        asset: str,
        client=None,
        raw_data_dir: Optional[Path] = None,
    ):
        super().__init__(market, asset)
        self.futures_code = self._get_futures_code(asset)
        self.xuntou_code = XUNTOU_MARKET_CODES.get(market.upper(), "SF")
        self.client = client
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
        """Get default input paths for minute data.

        Returns only input-read paths rooted at the constructor-supplied
        ``raw_data_dir`` (or the lazy fallback derived from ``PathsConfig.from_env()``).
        Output paths must be supplied explicitly — echolon no longer writes to
        the package install directory.
        """
        input_base = self._raw_data_dir / self.market / self.futures_code
        return {
            "main_contract": input_base / "main_contract.csv",
        }

    def set_client(self, client) -> None:
        """Set or replace the data client for API calls."""
        self.client = client

    def _require_client(self) -> None:
        """Raise RuntimeError if client is not set."""
        if self.client is None:
            raise RuntimeError(
                "Data client required but not set. "
                "Pass client (XtdcClient) to constructor or call set_client()."
            )

    def extract_raw(
        self,
        input_dir: Optional[str] = None,  # noqa: ARG002
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,  # noqa: ARG002
        end_date: Optional[str] = None,  # noqa: ARG002
        save: bool = True,
    ) -> None:
        """Not used for minute data; use extract_main_contract + download_minute_data.

        Raises:
            ValueError: always — minute extraction requires explicit output_dir and
                        is performed via extract_main_contract() + download_minute_data().
        """
        if save and output_dir is None:
            raise ValueError(
                "output_dir is required for extraction. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default. "
                "Use extract_main_contract(output_dir=...) + download_minute_data(output_dir=...) "
                "for minute data extraction."
            )
        _ = input_dir, start_date, end_date

    def extract_main_contract(
        self,
        input_dir: Optional[str] = None,  # noqa: ARG002
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,  # noqa: ARG002
        end_date: Optional[str] = None,  # noqa: ARG002
        save: bool = True
    ) -> pd.DataFrame:
        """
        Download main contract history via client.

        Args:
            input_dir: Not used for API extraction
            output_dir: Directory to save extracted data
            start_date: Not used
            end_date: Not used
            save: Whether to save extracted data (default True)

        Returns:
            DataFrame with main contract mapping
        """
        _ = input_dir, start_date, end_date

        if save and output_dir is None:
            raise ValueError(
                "output_dir is required. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default."
            )

        self._require_client()

        output_path = str(Path(output_dir)) if output_dir else None

        df = self.client.download_main_contract_history(
            futures_code=self.futures_code,
            xuntou_code=self.xuntou_code,
            output_dir=output_path if save else None,
        )

        if df is None or df.empty:
            logger.warning("[SHFE_MINUTE] No main contract data returned")
            return pd.DataFrame()

        logger.info(f"[SHFE_MINUTE] Main contract history: {len(df)} entries")
        return df

    def download_minute_data(
        self,
        start_contract: str = "2301",
        period: str = "1m",
        output_dir: Optional[str] = None
    ) -> bool:
        """
        Download minute OHLCV data for contracts.

        Requires an injected client conforming to `XtdataClient` protocol.
        The client manages the broker SDK connection; this method only calls
        data-retrieval methods on it.

        Args:
            start_contract: Starting contract code (e.g., '2301' for al2301)
            period: Data period ('1m', '5m', '15m', '1h')
            output_dir: Output directory

        Returns:
            True if successful
        """
        if output_dir is None:
            raise ValueError(
                "output_dir is required for download_minute_data. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default."
            )

        self._require_client()

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get main contracts
        full_contract = f"{self.futures_code}{start_contract}.{self.xuntou_code}"
        main_contracts = self._get_contracts_from_start(full_contract)

        if not main_contracts:
            logger.error(f"[SHFE_MINUTE] No contracts found from {full_contract}")
            return False

        logger.info(f"[SHFE_MINUTE] Downloading {len(main_contracts)} contracts")

        success_count = 0
        for idx, contract in enumerate(main_contracts, 1):
            logger.info(f"[SHFE_MINUTE] [{idx}/{len(main_contracts)}] Processing {contract}")

            try:
                # Download via injected client
                self.client.download_history_data(stock_code=contract, period=period)
                data_dict = self.client.get_market_data_ex([], [contract], period=period)

                if not data_dict or contract not in data_dict:
                    logger.warning(f"[SHFE_MINUTE] No data for {contract}")
                    continue

                df = data_dict[contract]
                if df.empty:
                    logger.warning(f"[SHFE_MINUTE] Empty data for {contract}")
                    continue

                # Save (strip market code from filename)
                contract_code = contract.split('.')[0]
                output_file = output_dir / f'{contract_code}.csv'
                df.to_csv(output_file, index=False, encoding='utf-8-sig')

                success_count += 1
                logger.info(f"[SHFE_MINUTE] Saved {len(df)} rows: {output_file.name}")

            except Exception as e:
                logger.error(f"[SHFE_MINUTE] Error for {contract}: {e}")
                continue

        logger.info(f"[SHFE_MINUTE] Complete: {success_count}/{len(main_contracts)} contracts")
        return success_count > 0

    def _get_contracts_from_start(self, start_contract: str) -> List[str]:
        """Get list of contracts starting from a specific contract."""
        paths = self._get_default_paths()
        csv_path = paths["main_contract"]

        if not csv_path.exists():
            logger.warning(f"[SHFE_MINUTE] Main contract file not found: {csv_path}")
            return []

        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        unique_contracts = df['main_contract'].drop_duplicates().tolist()

        if start_contract not in unique_contracts:
            logger.warning(f"[SHFE_MINUTE] Start contract {start_contract} not found")
            return []

        start_idx = unique_contracts.index(start_contract)
        return unique_contracts[start_idx:]

    def split_by_contract(
        self,
        data: pd.DataFrame = None,  # noqa: ARG002
        output_dir: Optional[str] = None  # noqa: ARG002
    ) -> list:
        """
        For minute data, splitting is done during download.
        This method is a no-op that returns empty list.
        """
        _ = data, output_dir
        logger.info("[SHFE_MINUTE] Minute data already split by contract during download")
        return []

    def generate_trading_calendar(
        self,
        data: pd.DataFrame = None,  # noqa: ARG002
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generate trading calendar from main contract file.

        Uses main_contract.csv to extract trading dates.
        Note: `data` parameter is ignored.
        """
        _ = data
        if output_dir is None:
            raise ValueError(
                "output_dir is required for generate_trading_calendar. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default."
            )

        paths = self._get_default_paths()
        output_dir = Path(output_dir)

        # Load main contract file (read from RAW_DATA_DIR by default)
        main_contract_file = paths["main_contract"]
        if not main_contract_file.exists():
            logger.error("[SHFE_MINUTE] Main contract file not found")
            return pd.DataFrame()

        df = pd.read_csv(main_contract_file, encoding='utf-8-sig')

        # Get unique dates
        df['date'] = pd.to_datetime(df['date'])
        trading_dates = df['date'].drop_duplicates().sort_values().tolist()

        # Filter by start date
        if start_date:
            start_dt = pd.to_datetime(start_date)
            trading_dates = [d for d in trading_dates if d >= start_dt]

        # Create calendar
        calendar = pd.DataFrame({
            'date': trading_dates,
            'is_trading_day': True
        })

        # Save
        calendar_path = output_dir / "trading_calendar.csv"
        calendar.to_csv(calendar_path, index=False)

        logger.info(f"[SHFE_MINUTE] Calendar saved: {calendar_path}")
        return calendar
