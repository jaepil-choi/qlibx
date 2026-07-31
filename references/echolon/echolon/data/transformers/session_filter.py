"""
Session Filter
==============

Filters OHLCV data to include only bars within valid trading sessions.
Removes bars during breaks and outside trading hours.
"""
import logging
from datetime import time
from typing import List, Optional, Tuple
import pandas as pd

# Import session definitions from centralized config
from echolon.config.markets.shfe.sessions import ALL_SESSIONS as SHFE_ALL_SESSIONS

logger = logging.getLogger(__name__)


class SessionFilter:
    """
    Filters OHLCV data based on trading session hours.

    Uses centralized session definitions from config/markets/{market}/sessions.py.
    Bars during breaks and outside trading hours are removed.
    """

    def __init__(self, market: str = "SHFE"):
        """
        Initialize session filter.

        Args:
            market: Market code to determine session windows
        """
        self.market = market.upper()
        self.sessions = self._get_market_sessions()

    def _get_market_sessions(self) -> List[Tuple[time, time, bool]]:
        """Get trading session windows for the market from centralized config."""
        if self.market == "SHFE":
            # Convert SessionWindow objects to tuples for filtering
            return [
                (s.start, s.end, s.crosses_midnight)
                for s in SHFE_ALL_SESSIONS
            ]
        # For crypto, return empty list (24/7 trading, no filtering needed)
        elif self.market in ("CRYPTO", "BINANCE"):
            return []  # No filtering for 24/7 markets
        else:
            logger.warning(f"[SESSION_FILTER] Unknown market {self.market}, using SHFE sessions")
            return [
                (s.start, s.end, s.crosses_midnight)
                for s in SHFE_ALL_SESSIONS
            ]

    def filter(
        self,
        df: pd.DataFrame,
        datetime_column: str = 'datetime'
    ) -> pd.DataFrame:
        """
        Filter DataFrame to include only bars within trading sessions.

        For SHFE market, also removes bars with suspend_flag = 1.

        Args:
            df: DataFrame with datetime column
            datetime_column: Name of datetime column

        Returns:
            Filtered DataFrame with only valid trading bars
        """
        if datetime_column not in df.columns:
            logger.warning(f"[SESSION_FILTER] Column '{datetime_column}' not found, skipping filter")
            return df

        if not self.sessions:
            logger.info(f"[SESSION_FILTER] No session filter for {self.market} (24/7 market)")
            return df

        result = df.copy()
        original_count = len(result)

        # Ensure datetime column is proper datetime type
        if not pd.api.types.is_datetime64_any_dtype(result[datetime_column]):
            result[datetime_column] = pd.to_datetime(result[datetime_column])

        # Extract time component
        bar_times = result[datetime_column].dt.time

        # Build mask for valid trading times
        valid_mask = pd.Series([False] * len(result), index=result.index)

        for session_start, session_end, crosses_midnight in self.sessions:
            if crosses_midnight:
                # Night session: 21:00-01:00 (time >= 21:00 OR time < 01:00)
                session_mask = (bar_times >= session_start) | (bar_times < session_end)
            else:
                # Normal session: start <= time < end
                session_mask = (bar_times >= session_start) & (bar_times < session_end)

            valid_mask = valid_mask | session_mask

        # For SHFE: also filter out suspended bars (suspend_flag = 1)
        suspended_count = 0
        if self.market == "SHFE" and 'suspend_flag' in result.columns:
            suspend_mask = result['suspend_flag'] == 1
            suspended_count = suspend_mask.sum()
            valid_mask = valid_mask & ~suspend_mask

        # Apply filter
        result = result[valid_mask].reset_index(drop=True)
        filtered_count = original_count - len(result)

        if filtered_count > 0:
            msg = f"[SESSION_FILTER] Filtered {filtered_count} bars ({original_count} → {len(result)})"
            if suspended_count > 0:
                msg += f" [including {suspended_count} suspended]"
            logger.info(msg)
        else:
            logger.info(f"[SESSION_FILTER] All {original_count} bars valid")

        return result

    def get_session_info(self) -> str:
        """Get human-readable session information."""
        if not self.sessions:
            return f"{self.market}: 24/7 trading (no session filter)"

        info_parts = []
        for start, end, crosses_midnight in self.sessions:
            if crosses_midnight:
                info_parts.append(f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')} (overnight)")
            else:
                info_parts.append(f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}")

        return f"{self.market}: " + ", ".join(info_parts)
