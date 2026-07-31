"""
Base Extractor Interface
========================

Extractors are responsible for retrieving raw market data from sources.

Separation of Concerns:
- Extractors: ONLY retrieve raw data from files/APIs
- Transformers: Process and standardize the data
- Loaders: Provide data access to consumers

Note: split_by_contract and generate_trading_calendar are provided as
convenience methods that delegate to transformer classes. Subclasses
can override if special handling is needed.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Protocol, Dict, Any, ClassVar, Set
import pandas as pd


class XtdataClient(Protocol):
    """Interface for MiniQMT / xtquant-style historical data clients.

    Echolon does not import xtquant directly — callers provide an object
    implementing this protocol. Typical implementations live in the consumer
    repo (e.g. goingmerry or direct MiniQMT integration).
    """

    def download_history_data(self, stock_code: str, period: str) -> None:
        """Trigger historical-data download for a given contract + period."""
        ...

    def get_market_data_ex(
        self, fields: List[str], stock_list: List[str], period: str
    ) -> Dict[str, Any]:
        """Return downloaded data. Mirror of xtdata.get_market_data_ex signature."""
        ...


class BaseExtractor(ABC):
    """
    Abstract base class for market data extractors.

    Extractors should focus on data retrieval only.
    Transformation is handled by transformer classes.

    Each subclass must declare a capabilities: ClassVar[Set[str]] indicating
    which operations it supports (e.g., 'batch', 'incremental', 'calendar_generate').
    Callers check capabilities rather than using hasattr() duck-typing.
    """

    capabilities: ClassVar[Set[str]] = set()  # Subclasses must override

    def __init__(self, market: str, asset: str):
        """
        Initialize extractor.

        Args:
            market: Market code (e.g., "SHFE", "CME")
            asset: Asset name (e.g., "aluminum", "copper")
        """
        self.market = market
        self.asset = asset

    @abstractmethod
    def extract_raw(
        self,
        input_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save: bool = True
    ) -> pd.DataFrame:
        """
        Extract raw market data from source files.

        This is the core extractor responsibility - getting raw data
        from exchange files, APIs, or other sources.

        Args:
            input_dir: Directory containing raw source files
            output_dir: Directory to save extracted data
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
            save: Whether to save extracted data to output_dir (default True)

        Returns:
            DataFrame with extracted OHLCV data
        """
        pass

    def split_by_contract(
        self,
        data: pd.DataFrame = None,
        output_dir: Optional[str] = None
    ) -> List[str]:
        """
        Split extracted data by contract using ContractSplitter transformer.

        Args:
            data: Extracted OHLCV data
            output_dir: Directory to save per-contract files

        Returns:
            List of contract names that were saved
        """
        from ..transformers.contract_splitter import ContractSplitter

        if data is None or data.empty:
            return []

        splitter = ContractSplitter(output_dir=output_dir)
        return splitter.split(data)

    def generate_trading_calendar(
        self,
        data: pd.DataFrame = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generate trading calendar using CalendarGenerator transformer.

        Args:
            data: Extracted OHLCV data
            output_dir: Directory to save calendar
            start_date: Optional start date filter

        Returns:
            DataFrame with trading dates
        """
        from ..transformers.calendar_generator import CalendarGenerator

        if data is None or data.empty:
            return pd.DataFrame()

        calendar_gen = CalendarGenerator(output_dir=output_dir)
        return calendar_gen.generate(df=data, start_date=start_date)
