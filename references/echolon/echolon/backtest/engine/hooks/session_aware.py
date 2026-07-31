"""
Session-Aware Hook
==================

Hook for intraday trading with session context support.

This hook adds:
1. Session context provider: Tracks bar position within trading sessions
2. Session-aware market data: Exposes VWAP, session high/low, session phase
3. Market-specific session handling: Uses market adapter's factory method

DESIGN PRINCIPLE:
    Infrastructure provides FACTUAL DATA only.
    Strategy decides how to interpret (opening phase, closing phase, etc.).

When to use:
- Intraday trading (any market)
- Strategies that need session context (bar position, session phase, etc.)
- NOT needed for interday/daily strategies

Session context provides FACTUAL data:
- session_type: 'night', 'day', 'continuous'
- session_phase: 'night', 'morning', 'afternoon', etc.
- bar_of_session: 0-indexed position within session
- bars_remaining: bars until session end
- gap_pct: gap from previous session
- session_high, session_low: session extremes
- vwap: session volume-weighted average price

Strategy decides:
- What constitutes "opening phase" (e.g., bar_of_session < 6)
- What constitutes "closing phase" (e.g., bars_remaining < 3)
- Opening range definition (strategy tracks first N bars)

Usage:
    hook = SessionAwareHook(
        market_adapter=shfe_adapter,
        bar_size_minutes=5,
    )
    engine.add_hook(hook)
"""

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import backtrader as bt
    from ..backtrader_engine import BacktraderEngine
    from echolon.markets.interface import IMarketAdapter
    from echolon.strategy.frequency.session_interface import ISessionContext

from .base import IEngineHook

logger = logging.getLogger(__name__)


class SessionAwareHook(IEngineHook):
    """
    Hook for intraday trading with session context awareness.

    Creates and connects a session context provider to the engine's
    market data component, enabling strategies to access FACTUAL data:
    - Session phase (from market config)
    - Bar position within session
    - Session high/low, VWAP

    DESIGN PRINCIPLE:
        Infrastructure provides factual data only.
        Strategy decides opening/closing phase thresholds.

    The actual session logic is market-specific and provided by
    the market adapter's create_session_provider() factory method.

    Parameters:
        market_adapter: Market adapter with session configuration
        bar_size_minutes: Bar size in minutes (default: 5)
    """

    def __init__(
        self,
        market_adapter: 'IMarketAdapter',
        bar_size_minutes: int = 5,
    ):
        self._market_adapter = market_adapter
        self._bar_size_minutes = bar_size_minutes

        # Created during on_init
        self._session_provider: Optional['ISessionContext'] = None
        self._provider_connected = False

    @property
    def name(self) -> str:
        return "SessionAwareHook"

    def on_init(self, engine: 'BacktraderEngine') -> None:
        """
        Create session context provider and connect to market data.
        """
        # Use market adapter's factory method to create market-specific provider
        self._session_provider = self._market_adapter.create_session_provider(
            bar_size_minutes=self._bar_size_minutes,
        )

        # Store in engine for direct access
        engine._session_context_provider = self._session_provider

        # Connect to market data component
        engine._market_data.set_session_context_provider(self._session_provider)
        self._provider_connected = True

        provider_class = self._session_provider.__class__.__name__
        logger.info(
            f"[{self.name}] {provider_class} created: "
            f"bar_size={self._bar_size_minutes}min"
        )

    def on_setup(self, cerebro: 'bt.Cerebro', engine: 'BacktraderEngine') -> None:
        """
        Session context is already set during on_init.
        Nothing additional needed during setup.
        """
        pass

    def on_post_setup(self, cerebro: 'bt.Cerebro', engine: 'BacktraderEngine') -> None:
        """
        Validate session provider is connected.
        """
        if not self._provider_connected:
            logger.warning(
                f"[{self.name}] Session provider was not connected to market data"
            )

    def on_pre_run(self, engine: 'BacktraderEngine') -> None:
        """
        Pre-run logging.
        """
        if self._session_provider is not None:
            sessions_per_day = self._session_provider.get_total_sessions_per_day()
            logger.debug(
                f"[{self.name}] Pre-run: {sessions_per_day} sessions per day"
            )

    def on_post_run(
        self,
        engine: 'BacktraderEngine',
        strategy: 'bt.Strategy',
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Add session-aware metadata to results.
        """
        results['session_aware_enabled'] = True
        results['session_awareness'] = {
            'provider_class': (
                self._session_provider.__class__.__name__
                if self._session_provider else None
            ),
            'bar_size_minutes': self._bar_size_minutes,
            'provider_connected': self._provider_connected,
        }

        logger.debug(f"[{self.name}] Post-run complete")

        return results

    def get_session_provider(self) -> Optional['ISessionContext']:
        """
        Get the session context provider.

        Returns:
            ISessionContext implementation or None if not initialized
        """
        return self._session_provider

    def __repr__(self) -> str:
        provider_class = (
            self._session_provider.__class__.__name__
            if self._session_provider else 'None'
        )
        return (
            f"SessionAwareHook("
            f"provider={provider_class}, "
            f"bar_size={self._bar_size_minutes}min)"
        )
