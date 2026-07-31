"""
Binance Perpetual Futures Data Extractor
========================================

Extracts OHLCV data from Binance USDT-Margined Perpetual Futures API.

Supported intervals: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M

API Documentation:
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data

Rate Limits:
- Limit 1-99: weight 1
- Limit 100-499: weight 2
- Limit 500-1000: weight 5
- Limit >1000: weight 10

Note: Maximum 1500 candles per request. For longer date ranges,
the extractor automatically paginates requests.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, ClassVar, Set

import pandas as pd
import requests

from ..base import BaseExtractor

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
KLINE_ENDPOINT = "/fapi/v1/klines"

# Valid kline intervals
VALID_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M"
]

# Interval to milliseconds mapping (for pagination calculation)
INTERVAL_MS: Dict[str, int] = {
    "1m": 60 * 1000,
    "3m": 3 * 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
    "8h": 8 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "3d": 3 * 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
    "1M": 30 * 24 * 60 * 60 * 1000,  # Approximate
}

# Symbol mapping for common names
SYMBOL_MAPPING: Dict[str, str] = {
    "btc": "BTCUSDT",
    "bitcoin": "BTCUSDT",
    "eth": "ETHUSDT",
    "ethereum": "ETHUSDT",
    "sol": "SOLUSDT",
    "solana": "SOLUSDT",
    "bnb": "BNBUSDT",
    "xrp": "XRPUSDT",
    "doge": "DOGEUSDT",
    "ada": "ADAUSDT",
    "avax": "AVAXUSDT",
    "link": "LINKUSDT",
}

# OHLCV column names for the response
OHLCV_COLUMNS = [
    "open_time",      # 0: Open time (ms)
    "open",           # 1: Open price
    "high",           # 2: High price
    "low",            # 3: Low price
    "close",          # 4: Close price
    "volume",         # 5: Volume (base asset)
    "close_time",     # 6: Close time (ms)
    "quote_volume",   # 7: Quote asset volume
    "trades",         # 8: Number of trades
    "taker_buy_vol",  # 9: Taker buy base asset volume
    "taker_buy_quote",# 10: Taker buy quote asset volume
    "ignore"          # 11: Unused field
]


class BinancePerpetualExtractor(BaseExtractor):
    """
    Extractor for Binance USDT-Margined Perpetual Futures data.

    This extractor:
    1. Connects to Binance Futures REST API (no authentication required for market data)
    2. Downloads historical kline/candlestick data
    3. Handles pagination for large date ranges
    4. Saves data in standardized OHLCV format

    Example usage:
        extractor = BinancePerpetualExtractor(market="CRYPTO", asset="btc")
        df = extractor.extract_raw(
            start_date="2024-01-01",
            end_date="2024-12-31",
            interval="4h"
        )

    Capabilities:
    - batch: extract all OHLCV data from source
    - calendar_generate: derives trading calendar from extracted data
    """

    capabilities: ClassVar[Set[str]] = {"batch", "calendar_generate"}

    def __init__(
        self,
        market: str = "CRYPTO",
        asset: str = "btc",
        interval: str = "4h",
        raw_data_dir: Optional[Path] = None,
    ):
        """
        Initialize the Binance perpetual extractor.

        Args:
            market: Market code (default "CRYPTO")
            asset: Asset name (e.g., "btc", "eth", "sol") or full symbol (e.g., "BTCUSDT")
            interval: Default kline interval (default "4h")
            raw_data_dir: Base raw-data directory used for default output paths.
                When None, falls back to ``PathsConfig.from_env()``.
        """
        super().__init__(market, asset)
        self.symbol = self._normalize_symbol(asset)
        self.interval = self._validate_interval(interval)
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "DolphinQuantStrategy/1.0"
        })
        if raw_data_dir is None:
            from echolon.config.paths_config import PathsConfig
            raw_data_dir = PathsConfig.from_env().raw_data_dir
        self._raw_data_dir = Path(raw_data_dir)

    def _normalize_symbol(self, asset: str) -> str:
        """
        Normalize asset name to Binance symbol format.

        Args:
            asset: Asset name or symbol

        Returns:
            Binance symbol (e.g., "BTCUSDT")
        """
        asset_lower = asset.lower()

        # Check mapping first
        if asset_lower in SYMBOL_MAPPING:
            return SYMBOL_MAPPING[asset_lower]

        # If already in correct format
        if asset.upper().endswith("USDT"):
            return asset.upper()

        # Assume USDT pair
        return f"{asset.upper()}USDT"

    def _validate_interval(self, interval: str) -> str:
        """Validate and return the interval."""
        if interval not in VALID_INTERVALS:
            raise ValueError(
                f"Invalid interval: {interval}. "
                f"Valid intervals: {VALID_INTERVALS}"
            )
        return interval

    def _get_default_paths(self) -> dict:
        """Get default paths for crypto data."""
        output_base = self._raw_data_dir / "CRYPTO" / self.symbol
        return {
            "output_dir": output_base,
            "ohlcv_data": output_base / "ohlcv",
        }

    def _datetime_to_ms(self, dt: datetime) -> int:
        """Convert datetime to milliseconds timestamp."""
        return int(dt.timestamp() * 1000)

    def _ms_to_datetime(self, ms: int) -> datetime:
        """Convert milliseconds timestamp to datetime."""
        return datetime.fromtimestamp(ms / 1000)

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime."""
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {date_str}")

    def _fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1500
    ) -> List[List[Any]]:
        """
        Fetch klines from Binance API.

        Args:
            symbol: Trading pair symbol
            interval: Kline interval
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            limit: Number of klines to fetch (max 1500)

        Returns:
            List of kline data arrays
        """
        url = f"{BINANCE_FUTURES_BASE_URL}{KLINE_ENDPOINT}"

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1500),
        }

        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"[BINANCE] API request failed: {e}")
            raise

    def extract_raw(
        self,
        input_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save: bool = True,
        interval: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Extract OHLCV data from Binance Futures API.

        Args:
            input_dir: Not used for API extraction
            output_dir: Directory to save extracted data
            start_date: Start date (YYYY-MM-DD), defaults to 2 years ago
            end_date: End date (YYYY-MM-DD), defaults to now
            save: Whether to save extracted data (default True)
            interval: Kline interval (overrides constructor default)

        Returns:
            DataFrame with OHLCV data
        """
        # input_dir not used for API extraction
        _ = input_dir

        # Use provided interval or default
        interval = self._validate_interval(interval) if interval else self.interval

        # Parse dates
        if end_date:
            end_dt = self._parse_date(end_date)
        else:
            end_dt = datetime.now()

        if start_date:
            start_dt = self._parse_date(start_date)
        else:
            # Default to 2 years of data
            start_dt = end_dt - timedelta(days=730)

        start_ms = self._datetime_to_ms(start_dt)
        end_ms = self._datetime_to_ms(end_dt)

        logger.info(
            f"[BINANCE] Extracting {self.symbol} {interval} data "
            f"from {start_dt.date()} to {end_dt.date()}"
        )

        # Fetch data with pagination
        all_klines = []
        current_start = start_ms
        request_count = 0
        max_requests = 1000  # Safety limit

        while current_start < end_ms and request_count < max_requests:
            klines = self._fetch_klines(
                symbol=self.symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_ms,
                limit=1500
            )

            if not klines:
                break

            all_klines.extend(klines)
            request_count += 1

            # Move start to after the last candle
            last_close_time = klines[-1][6]  # close_time is index 6
            current_start = last_close_time + 1

            # Rate limiting: sleep briefly between requests
            if request_count % 10 == 0:
                logger.info(f"[BINANCE] Fetched {len(all_klines)} candles...")
                time.sleep(0.5)

            # If we got fewer than limit, we've reached the end
            if len(klines) < 1500:
                break

        if not all_klines:
            logger.warning(f"[BINANCE] No data returned for {self.symbol}")
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(all_klines, columns=OHLCV_COLUMNS)

        # Convert types
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

        numeric_cols = ["open", "high", "low", "close", "volume",
                       "quote_volume", "trades", "taker_buy_vol", "taker_buy_quote"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop the unused column
        df = df.drop(columns=["ignore"])

        # Add metadata columns
        df["symbol"] = self.symbol
        df["interval"] = interval

        # Create standardized datetime column
        df["datetime"] = df["open_time"]
        df["date"] = df["datetime"].dt.date

        # Remove duplicates (can happen at pagination boundaries)
        df = df.drop_duplicates(subset=["open_time"], keep="first")

        # Sort by time
        df = df.sort_values("open_time").reset_index(drop=True)

        logger.info(
            f"[BINANCE] Extracted {len(df)} candles for {self.symbol} "
            f"({df['datetime'].min()} to {df['datetime'].max()})"
        )

        # Save if requested
        if save:
            if output_dir is None:
                raise ValueError(
                    "output_dir is required when save=True. Pass an explicit path — "
                    "echolon no longer writes to the package install directory by default. "
                    "Typical convention: MARKET_DATA_DIR / 'CRYPTO' / symbol"
                )
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Filename includes symbol and interval
            filename = f"{self.symbol}_{interval}.csv"
            output_file = output_path / filename

            df.to_csv(output_file, index=False)
            logger.info(f"[BINANCE] Saved to {output_file}")

        return df

    def download_multiple_intervals(
        self,
        intervals: List[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_dir: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Download data for multiple intervals.

        Args:
            intervals: List of intervals to download (default: ["1h", "4h", "1d"])
            start_date: Start date
            end_date: End date
            output_dir: Output directory

        Returns:
            Dictionary mapping interval to DataFrame
        """
        if intervals is None:
            intervals = ["1h", "4h", "1d"]

        results = {}
        for interval in intervals:
            logger.info(f"[BINANCE] Downloading {self.symbol} {interval}...")
            df = self.extract_raw(
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                output_dir=output_dir,
                save=True
            )
            results[interval] = df
            time.sleep(1)  # Rate limiting between intervals

        return results

    def get_available_symbols(self) -> List[str]:
        """
        Get list of available USDT-margined perpetual symbols.

        Returns:
            List of symbol names
        """
        url = f"{BINANCE_FUTURES_BASE_URL}/fapi/v1/exchangeInfo"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            symbols = [
                s["symbol"] for s in data.get("symbols", [])
                if s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
            ]

            return sorted(symbols)

        except requests.exceptions.RequestException as e:
            logger.error(f"[BINANCE] Failed to fetch symbols: {e}")
            return []

    def split_by_contract(
        self,
        data: pd.DataFrame = None,
        output_dir: Optional[str] = None
    ) -> list:
        """
        Not applicable for perpetual futures (no contract expiry).
        Returns empty list.
        """
        _ = data, output_dir
        logger.info("[BINANCE] Perpetual futures have no contract expiry - no split needed")
        return []

    def generate_trading_calendar(
        self,
        data: pd.DataFrame = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Generate trading calendar from extracted data.

        For crypto, every day is a trading day (24/7).

        Args:
            data: Extracted OHLCV data
            output_dir: Directory to save calendar
            start_date: Optional start date filter

        Returns:
            DataFrame with trading dates
        """
        if data is None or data.empty:
            logger.warning("[BINANCE] No data provided for calendar generation")
            return pd.DataFrame()

        if output_dir is None:
            raise ValueError(
                "output_dir is required for generate_trading_calendar. Pass an explicit path — "
                "echolon no longer writes to the package install directory by default."
            )
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get unique dates from data
        if "date" in data.columns:
            dates = pd.to_datetime(data["date"]).drop_duplicates().sort_values()
        elif "datetime" in data.columns:
            dates = data["datetime"].dt.date.drop_duplicates().sort_values()
            dates = pd.to_datetime(dates)
        else:
            logger.warning("[BINANCE] No date column found in data")
            return pd.DataFrame()

        # Filter by start date
        if start_date:
            start_dt = pd.to_datetime(start_date)
            dates = dates[dates >= start_dt]

        # Create calendar
        calendar = pd.DataFrame({
            "date": dates,
            "is_trading_day": True,
            "market": "CRYPTO",
            "symbol": self.symbol
        })

        # Save
        calendar_file = output_dir / "trading_calendar.csv"
        calendar.to_csv(calendar_file, index=False)
        logger.info(f"[BINANCE] Calendar saved: {calendar_file}")

        return calendar


# =============================================================================
# Convenience function for quick extraction
# =============================================================================

def extract_binance_ohlcv(
    symbol: str = "BTCUSDT",
    interval: str = "4h",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    output_dir: Optional[str] = None,
    save: bool = True
) -> pd.DataFrame:
    """
    Convenience function to extract Binance OHLCV data.

    Args:
        symbol: Trading pair (e.g., "BTCUSDT", "btc", "bitcoin")
        interval: Kline interval (e.g., "1h", "4h", "1d")
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        output_dir: Output directory
        save: Whether to save to CSV

    Returns:
        DataFrame with OHLCV data

    Example:
        # Download 1 year of 4-hour BTC data
        df = extract_binance_ohlcv(
            symbol="btc",
            interval="4h",
            start_date="2024-01-01",
            end_date="2024-12-31"
        )
    """
    extractor = BinancePerpetualExtractor(
        market="CRYPTO",
        asset=symbol,
        interval=interval
    )

    return extractor.extract_raw(
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        save=save,
        interval=interval
    )


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # Create extractor for Bitcoin
    extractor = BinancePerpetualExtractor(
        market="CRYPTO",
        asset="btc",
        interval="4h"
    )

    # Download 4-hour data for the last year
    df = extractor.extract_raw(
        start_date="2023-01-01",
        end_date="2025-12-31",
        save=True
    )

    print(f"\nExtracted {len(df)} candles")
    print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
    print(f"\nSample data:")
    print(df.head())
