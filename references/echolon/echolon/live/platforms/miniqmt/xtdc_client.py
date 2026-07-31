"""
XtDataCenter Client
===================

Token-based data client using xtdatacenter (xtdc) for market data access.

This is a lightweight alternative to MiniQMTClient for data-only operations.
It connects to xuntou's remote data service via token authentication, without
requiring the miniQMT desktop client to be running.

Key difference from MiniQMTClient:
- MiniQMTClient: connects to local miniQMT desktop via xttrader + xtdata
- XtdcClient: connects to remote xuntou servers via xtdatacenter token + xtdata

Both expose the same data methods (get_market_data, extract_dataframe_from_data)
so they can be used interchangeably as the `client` parameter in run_data_pipeline().

Additionally provides download_main_contract_history() which requires the
token-based API (historymaincontract is not available via miniQMT).

Configuration
-------------

Credentials are NEVER hardcoded in this open-source module. They MUST be
supplied at instantiation time via either:

1. Constructor kwargs: ``XtdcClient(token=..., addr_list=[...])``
2. Environment variables: ``XUNTOU_TOKEN``, ``XUNTOU_ADDR_LIST`` (comma-
   separated ``host:port`` items), and optionally ``XUNTOU_PORT``.

If neither source provides a token, ``connect()`` raises ``XtdcCredentialsMissing``.

Downstream private deployments (e.g. the ``goingmerry`` repo) are responsible
for materialising these values at runtime — typically by reading a local
credentials file that's excluded from version control. See
``goingmerry/credentials.py`` for the canonical loader pattern.

Usage:
    # In a private deployment (e.g. goingmerry):
    from goingmerry.credentials import load_xtdc_credentials
    creds = load_xtdc_credentials()
    client = XtdcClient(**creds)
    client.connect()
    # ...
    client.disconnect()
"""

import datetime
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Default port for xtdatacenter listener (the port itself isn't a secret;
# the token + addr_list are what need to be supplied externally).
XTDC_DEFAULT_PORT = 58615


class XtdcCredentialsMissing(RuntimeError):
    """Raised when XtdcClient is constructed without credentials and no
    XUNTOU_TOKEN / XUNTOU_ADDR_LIST env vars are set either."""


class XtdcClient:
    """
    Token-based xtdatacenter client for market data.

    Provides the same data interface as MiniQMTClient (get_market_data,
    extract_dataframe_from_data) so it can be passed to run_data_pipeline()
    via extractor.set_client().

    The xtdc listener (xtdc.init + xtdc.listen) is initialized once per
    process and kept alive. Only the xtdata client connection is
    opened/closed on each connect()/disconnect() cycle. This avoids
    port-conflict errors when the same long-running process (e.g.
    portfolio_runner with APScheduler) calls connect() on multiple days.
    """

    # Class-level flag: xtdc listener initialized once per process
    _listener_ready = False

    def __init__(
        self,
        token: Optional[str] = None,
        addr_list: Optional[Sequence[str]] = None,
        port: Optional[int] = None,
    ):
        """Construct a token-authenticated xtdc data client.

        Credentials may come from constructor kwargs (preferred) or from
        environment variables. See module docstring for details.

        Args:
            token: Xuntou authentication token. Falls back to
                ``$XUNTOU_TOKEN``. If neither is set, ``connect()`` raises.
            addr_list: List of ``host:port`` Xuntou data server addresses.
                Falls back to ``$XUNTOU_ADDR_LIST`` (comma-separated).
                Empty / unset means "let xtdc pick its default" — typical
                production deployments must specify these.
            port: Local listener port. Falls back to ``$XUNTOU_PORT``,
                then to ``XTDC_DEFAULT_PORT`` (58615).
        """
        self._token = token if token is not None else os.environ.get("XUNTOU_TOKEN", "")
        if addr_list is not None:
            self._addr_list = list(addr_list)
        else:
            env_addrs = os.environ.get("XUNTOU_ADDR_LIST", "")
            self._addr_list = [a.strip() for a in env_addrs.split(",") if a.strip()]
        if port is not None:
            self._port = int(port)
        else:
            env_port = os.environ.get("XUNTOU_PORT", "")
            self._port = int(env_port) if env_port else XTDC_DEFAULT_PORT
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _ensure_listener(self) -> None:
        """Initialize xtdc listener once per process.

        Subsequent calls are no-ops. The listener stays alive for the
        lifetime of the process so that daily xtdata reconnections can
        reuse the same port without conflict.

        Raises:
            XtdcCredentialsMissing: when no token has been supplied via
                constructor kwargs or ``$XUNTOU_TOKEN`` env var.
        """
        if XtdcClient._listener_ready:
            return

        if not self._token:
            raise XtdcCredentialsMissing(
                "XtdcClient: no token supplied. Pass token= to the "
                "constructor or set $XUNTOU_TOKEN before connecting. "
                "Tokens MUST NOT be hardcoded in this open-source module."
            )

        from xtquant import xtdatacenter as xtdc

        xtdc.set_token(self._token)
        xtdc.set_quote_time_mode_v2(True)

        if self._addr_list:
            xtdc.set_allow_optmize_address(list(self._addr_list))
        else:
            logger.warning(
                "[XTDC] No addr_list supplied (constructor or "
                "$XUNTOU_ADDR_LIST); xtdc will use its built-in defaults."
            )

        xtdc.set_index_mirror_enabled(True)
        xtdc.set_future_realtime_mode(True)
        xtdc.init(False)
        xtdc.listen(port=self._port)

        XtdcClient._listener_ready = True
        logger.info("[XTDC] Listener initialized on port %d", self._port)

    def connect(self) -> bool:
        """Connect to xuntou data service via xtdatacenter token.

        Returns:
            True if connection successful.
        """
        if self._connected:
            return True

        try:
            self._ensure_listener()

            from xtquant import xtdata
            # xtdata.connect() returns an already-connected client without
            # honoring a newly supplied port.  A process that queried MiniQMT
            # first would otherwise stay on the broker port instead of this
            # token listener.
            xtdata.disconnect()
            xtdata.connect(port=self._port)

            self._connected = True
            logger.info("[XTDC] Connected on port %d", self._port)
            return True

        except XtdcCredentialsMissing:
            # Re-raise — calling code must handle missing-credentials
            # explicitly so it's never silently skipped.
            raise
        except ImportError:
            logger.error("[XTDC] xtquant library not installed")
            raise
        except Exception as e:
            logger.error("[XTDC] Connection failed: %s", e)
            return False

    def disconnect(self) -> None:
        """Disconnect xtdata client. The xtdc listener stays alive."""
        if not self._connected:
            return
        try:
            from xtquant import xtdata
            xtdata.disconnect()
            self._connected = False
            logger.info("[XTDC] Disconnected")
        except Exception as e:
            logger.warning("[XTDC] Disconnect failed: %s", e)

    def shutdown(self) -> bool:
        """Disconnect and stop the token data listener for finite processes.

        Long-running services should continue to use disconnect(), which keeps
        the listener reusable. One-shot probes and scheduled batch jobs should
        use shutdown() so native xtdatacenter threads do not survive into
        interpreter teardown.
        """
        listener_was_ready = type(self)._listener_ready
        self.disconnect()
        if not listener_was_ready:
            return True
        try:
            from xtquant import xtdatacenter as xtdc

            xtdc.shutdown()
            return True
        except AttributeError:
            logger.warning(
                "[XTDC] Installed datacenter binary has no shutdown symbol; "
                "caller must use a controlled process exit after flushing output"
            )
            return False
        finally:
            type(self)._listener_ready = False

    # ------------------------------------------------------------------
    # Main contract history (token-only API)
    # ------------------------------------------------------------------

    def download_main_contract_history(
        self,
        futures_code: str,
        xuntou_code: str,
        output_dir: Optional[str] = None,
    ) -> pd.DataFrame:
        """Download main contract history via xtdatacenter.

        This data is only available through the token-based API,
        not through the miniQMT desktop connection.

        Args:
            futures_code: Futures product code (e.g. 'al', 'cu').
            xuntou_code: Exchange code (e.g. 'SF').
            output_dir: If provided, saves main_contract.csv there.

        Returns:
            DataFrame with columns [date, main_contract].
        """
        from xtquant import xtdata

        symbol = f"{futures_code}00.{xuntou_code}"
        period = "historymaincontract"

        logger.info("[XTDC] Downloading main contract history for %s", symbol)

        xtdata.download_history_data(symbol, period, '', '')
        data_dict = xtdata.get_market_data_ex([], [symbol], period)

        if not data_dict or symbol not in data_dict:
            logger.warning("[XTDC] No main contract data for %s", symbol)
            return pd.DataFrame()

        df = data_dict[symbol].copy()

        df['date'] = pd.to_datetime(df['time'], unit='ms')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        df_filtered = df[['date', '期货统一规则代码']].copy()
        df_filtered.rename(
            columns={'期货统一规则代码': 'main_contract'}, inplace=True,
        )

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            csv_path = out_path / "main_contract.csv"
            df_filtered.to_csv(csv_path, index=False, encoding='utf-8-sig')
            logger.info("[XTDC] Main contract saved: %s (%d entries)", csv_path, len(df_filtered))

        return df_filtered

    def get_stock_list_in_sector(self, sector: str) -> List[str]:
        """Get all stock/futures codes in a sector.

        Args:
            sector: Sector code (e.g. 'SF' for SHFE futures).

        Returns:
            List of contract codes (e.g. ['al2507.SF', ...]).
        """
        from xtquant import xtdata

        try:
            result = xtdata.get_stock_list_in_sector(sector)
            return result if result else []
        except Exception as exc:
            logger.error("[XTDC] Failed to get stock list in sector %s: %s", sector, exc)
            return []

    # ------------------------------------------------------------------
    # Market data (same interface as MiniQMTClient)
    # ------------------------------------------------------------------

    def download_history_data(
        self,
        symbols: Union[str, List[str]],
        period: str = "1d",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        count: int = -1,
    ) -> bool:
        """Download historical market data via xtdata.

        Same interface as MiniQMTClient.download_history_data().
        """
        from xtquant import xtdata

        try:
            if isinstance(symbols, str):
                symbols = [symbols]

            logger.info(
                "Downloading historical data for %s, period: %s", symbols, period
            )

            for symbol in symbols:
                result = xtdata.download_history_data(
                    stock_code=symbol,
                    period=period,
                    start_time=start_time,
                    end_time=end_time,
                )
                logger.info("Download result for %s: %s", symbol, result)

            logger.info("Historical data download completed")
            return True

        except Exception as exc:
            logger.error("Failed to download historical data: %s", exc)
            return False

    def get_market_data(
        self,
        symbols: Union[str, List[str]],
        period: str = "1d",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """Get market data. Same interface as MiniQMTClient.get_market_data()."""
        from xtquant import xtdata

        try:
            if isinstance(symbols, str):
                symbols = [symbols]

            if not end_time:
                end_time = datetime.datetime.now().strftime("%Y%m%d")

            self.download_history_data(symbols, period, start_time, end_time)

            market_data = xtdata.get_market_data_ex(
                field_list=[],
                stock_list=symbols,
                period=period,
                start_time=start_time,
                end_time=end_time,
            )

            logger.info("Retrieved market data for %s", symbols)
            return market_data

        except Exception as exc:
            logger.error("Failed to get market data: %s", exc)
            return None

    def extract_dataframe_from_data(
        self,
        market_data: Dict,
        symbol: str,
    ) -> Optional[pd.DataFrame]:
        """Extract DataFrame from market data dict.

        Same interface as MiniQMTClient.extract_dataframe_from_data().
        """
        if not market_data or not isinstance(market_data, dict):
            logger.error("Invalid market data format")
            return None

        if symbol not in market_data:
            logger.error(
                "Symbol %s not found in data. Available: %s",
                symbol, list(market_data.keys()),
            )
            return None

        symbol_data = market_data[symbol]

        required_fields = ["open", "high", "low", "close", "volume"]
        if not all(field in symbol_data for field in required_fields):
            logger.error(
                "Missing required fields for %s. Available: %s",
                symbol, list(symbol_data.keys()),
            )
            return None

        try:
            timestamps = list(symbol_data["close"].keys())
            if not timestamps:
                logger.error("No timestamp data found for %s", symbol)
                return None

            dates = pd.to_datetime(timestamps, format="%Y%m%d")

            df_data = {}
            for field in required_fields:
                field_data = symbol_data[field]
                values = [field_data.get(ts, None) for ts in timestamps]
                df_data[field] = values

            df = pd.DataFrame(df_data, index=dates)

            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

            df = df.dropna()

            if df.empty:
                logger.error("No valid data after cleaning for %s", symbol)
                return None

            df = df.sort_index()
            logger.info(
                "Extracted DataFrame for %s: %d bars from %s to %s",
                symbol, len(df), df.index[0], df.index[-1],
            )
            return df

        except Exception as exc:
            logger.error("Failed to extract DataFrame for %s: %s", symbol, exc)
            return None
