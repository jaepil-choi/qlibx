"""
SHFE Session Availability Analyzer
===================================

Analyzes OHLCV data to detect which trading sessions were active for each
trading date. This handles irregular session availability due to holidays.

SHFE Session Structure:
- Night session (21:00-01:00) belongs to NEXT trading date
- Day session (09:00-15:00) belongs to same calendar date

Holiday Impact:
- Before major holidays: No night session (next day is holiday)
- After holidays: No night session for first trading day

Uses session definitions from: config/markets/shfe/phases.py
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import time

import pandas as pd

# Import session definitions from single source of truth
from echolon.config.markets.shfe.phases import (
    PHASES,
    TRADEABLE_PHASES,
    PHASE_TRADING_MINUTES,
    get_phase_trading_bars,
    get_tradeable_phases,
    is_aggregated_bar_size,
)

logger = logging.getLogger(__name__)


class SHFESessionAnalyzer:
    """
    Analyzes minute OHLCV data to derive session availability per trading date.

    This handles the SHFE calendar irregularity where some trading dates
    don't have all sessions (e.g., no night session before holidays).

    Output adds session availability columns to trading calendar:
    - has_night: Boolean, whether night session existed
    - has_morning: Boolean, whether morning session existed
    - has_afternoon: Boolean, whether afternoon session existed
    - night_bars: Actual bar count in night session
    - morning_bars: Actual bar count in morning session
    - afternoon_bars: Actual bar count in afternoon session
    - total_bars: Total bars for the trading date
    - sessions_active: List of active session names
    """

    def __init__(self, bar_size_minutes: int, bar_size: Optional[str] = None):
        """
        Initialize analyzer.

        Args:
            bar_size_minutes: Bar size in minutes (required - no default to ensure frequency-agnostic)
            bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                      For 30m/1h, uses aggregated phases (night_session, day_session).
                      For 5m/15m or None, uses granular phases (night, morning, afternoon).
        """
        self.bar_size_minutes = bar_size_minutes
        self.bar_size = bar_size

        # Get tradeable phases based on bar_size
        self.tradeable_phases = get_tradeable_phases(bar_size)
        self.is_aggregated = is_aggregated_bar_size(bar_size) if bar_size else False

        # Expected bar counts per session (from source of truth)
        self.expected_bars = {
            phase: get_phase_trading_bars(phase, bar_size_minutes, bar_size=bar_size)
            for phase in self.tradeable_phases
        }
        phase_type = "aggregated" if self.is_aggregated else "granular"
        logger.info(
            f"[SESSION_ANALYZER] Expected bars per session ({bar_size_minutes}min, {phase_type}): "
            f"{self.expected_bars}"
        )

    def analyze_from_ohlcv(
        self,
        df: pd.DataFrame,
        session_phase_column: str = 'session_phase',
        trading_date_column: str = 'trading_date'
    ) -> pd.DataFrame:
        """
        Analyze session availability from standardized OHLCV data.

        The OHLCV data must be standardized with:
        - trading_date: Trading date (YYYYMMDD format)
        - session_phase: Session phase name ('night', 'morning', 'afternoon', etc.)

        Args:
            df: Standardized OHLCV DataFrame
            session_phase_column: Column name for session phase
            trading_date_column: Column name for trading date

        Returns:
            DataFrame with one row per trading date and session availability columns
        """
        required_cols = [trading_date_column, session_phase_column]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        logger.info(f"[SESSION_ANALYZER] Analyzing {len(df)} bars across "
                   f"{df[trading_date_column].nunique()} trading dates")

        # Group by trading date and session phase to count bars
        session_counts = df.groupby(
            [trading_date_column, session_phase_column]
        ).size().unstack(fill_value=0)

        # Build result DataFrame
        result = pd.DataFrame(index=session_counts.index)
        result.index.name = 'trading_date'

        # Add session availability and bar counts (uses instance tradeable_phases)
        for phase in self.tradeable_phases:
            col_has = f'has_{phase}'
            col_bars = f'{phase}_bars'

            if phase in session_counts.columns:
                result[col_bars] = session_counts[phase]
                # Session is "active" if it has at least 50% of expected bars
                min_bars = max(1, self.expected_bars[phase] // 2)
                result[col_has] = session_counts[phase] >= min_bars
            else:
                result[col_bars] = 0
                result[col_has] = False

        # Calculate total bars
        bar_cols = [f'{phase}_bars' for phase in self.tradeable_phases]
        result['total_bars'] = result[bar_cols].sum(axis=1)

        # Build sessions_active list
        def get_active_sessions(row):
            active = []
            for phase in self.tradeable_phases:
                if row[f'has_{phase}']:
                    active.append(phase)
            return active

        result['sessions_active'] = result.apply(get_active_sessions, axis=1)

        # Reset index to make trading_date a column
        result = result.reset_index()

        # Convert trading_date to standard format
        result['trading_date'] = result['trading_date'].astype(str)

        logger.info(f"[SESSION_ANALYZER] Analyzed {len(result)} trading dates")
        self._log_summary(result)

        return result

    def _log_summary(self, result: pd.DataFrame) -> None:
        """Log summary statistics about session availability."""
        total_dates = len(result)

        for phase in self.tradeable_phases:
            has_col = f'has_{phase}'
            if has_col in result.columns:
                count = result[has_col].sum()
                pct = count / total_dates * 100 if total_dates > 0 else 0
                logger.info(
                    f"[SESSION_ANALYZER] {phase}: {count}/{total_dates} "
                    f"({pct:.1f}%) trading dates"
                )

        # Log dates without night session (likely pre-holiday)
        # Works for both granular ('has_night') and aggregated ('has_night_session')
        night_col = 'has_night_session' if self.is_aggregated else 'has_night'
        if night_col in result.columns:
            no_night = result[~result[night_col]]
            if len(no_night) > 0:
                sample_dates = no_night['trading_date'].head(10).tolist()
                logger.info(
                    f"[SESSION_ANALYZER] Dates without night session: "
                    f"{len(no_night)} dates (sample: {sample_dates[:5]})"
                )

    def enhance_calendar(
        self,
        calendar_df: pd.DataFrame,
        session_info_df: pd.DataFrame,
        date_column: str = 'date'
    ) -> pd.DataFrame:
        """
        Enhance trading calendar with session availability information.

        Args:
            calendar_df: Trading calendar DataFrame with date column
            session_info_df: Session info from analyze_from_ohlcv()
            date_column: Name of date column in calendar

        Returns:
            Enhanced calendar with session availability columns
        """
        result = calendar_df.copy()

        # Build columns to merge dynamically based on phases
        has_cols = [f'has_{phase}' for phase in self.tradeable_phases]
        bar_cols = [f'{phase}_bars' for phase in self.tradeable_phases]
        merge_cols = has_cols + bar_cols + ['total_bars', 'sessions_active']

        # Drop existing session columns if they exist (from previous runs)
        existing_cols = [col for col in merge_cols if col in result.columns]
        if existing_cols:
            logger.info(f"[SESSION_ANALYZER] Dropping existing session columns: {existing_cols}")
            result = result.drop(columns=existing_cols)

        # Ensure date formats match for merge
        if date_column in result.columns:
            result['_merge_date'] = pd.to_datetime(result[date_column]).dt.strftime('%Y%m%d')
        else:
            raise ValueError(f"Date column '{date_column}' not found in calendar")

        session_info = session_info_df.copy()
        session_info['_merge_date'] = session_info['trading_date'].astype(str)

        # Only merge columns that exist in session_info
        available_merge_cols = [c for c in merge_cols if c in session_info.columns]
        result = result.merge(
            session_info[['_merge_date'] + available_merge_cols],
            on='_merge_date',
            how='left'
        )

        # Fill NaN for dates not in session_info (shouldn't happen normally)
        for col in has_cols:
            if col in result.columns:
                result[col] = result[col].fillna(False)

        for col in bar_cols + ['total_bars']:
            if col in result.columns:
                result[col] = result[col].fillna(0).astype(int)

        if 'sessions_active' in result.columns:
            result['sessions_active'] = result['sessions_active'].apply(
                lambda x: x if isinstance(x, list) else []
            )

        # Clean up merge column
        result = result.drop(columns=['_merge_date'])

        logger.info(f"[SESSION_ANALYZER] Enhanced calendar with {len(result)} dates")
        return result

    def save_session_info(
        self,
        session_info: pd.DataFrame,
        output_path: Path,
        filename: str = 'session_availability.csv'
    ) -> Path:
        """
        Save session availability information to CSV.

        Args:
            session_info: Session info DataFrame
            output_path: Output directory
            filename: Output filename

        Returns:
            Path to saved file
        """
        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        file_path = output_path / filename

        # Convert sessions_active list to string for CSV
        save_df = session_info.copy()
        if 'sessions_active' in save_df.columns:
            save_df['sessions_active'] = save_df['sessions_active'].apply(
                lambda x: ','.join(x) if isinstance(x, list) else ''
            )

        save_df.to_csv(file_path, index=False)
        logger.info(f"[SESSION_ANALYZER] Saved session info: {file_path}")

        return file_path


def analyze_shfe_sessions(
    ohlcv_file: str,
    output_dir: str,
    bar_size_minutes: int,
    bar_size: Optional[str] = None
) -> pd.DataFrame:
    """
    Convenience function to analyze SHFE session availability from OHLCV file.

    Args:
        ohlcv_file: Path to standardized OHLCV CSV file
        output_dir: Directory to save session info
        bar_size_minutes: Bar size in minutes (required - no default to ensure frequency-agnostic)
        bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                  For 30m/1h, uses aggregated phases (night_session, day_session).
                  For 5m/15m or None, uses granular phases (night, morning, afternoon).

    Returns:
        Session info DataFrame
    """
    logger.info(f"[SESSION_ANALYZER] Loading OHLCV from: {ohlcv_file}")

    df = pd.read_csv(ohlcv_file)

    analyzer = SHFESessionAnalyzer(bar_size_minutes=bar_size_minutes, bar_size=bar_size)
    session_info = analyzer.analyze_from_ohlcv(df)

    # Save results
    output_path = Path(output_dir)
    analyzer.save_session_info(session_info, output_path)

    return session_info
