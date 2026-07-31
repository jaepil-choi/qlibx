"""
Engine Factory
==============

Factory for creating trading engines with appropriate adapters and contexts.

Responsibilities:
- Create market adapters based on market type (SHFE, crypto)
- Create frequency contexts based on trading frequency (interday, intraday)
- Compose engine hooks based on trading mode
- Assemble and return configured trading engines (backtest or deploy)

TradingContext as Single Source of Truth:
    All engine creation methods accept TradingContext (ctx) as the primary parameter.
    The ctx provides market, instrument, and frequency configuration.

Hook Composition Logic:
    The factory decides which hooks to add based on trading mode:

    | Market | Frequency | ContractAwareHook | SessionAwareHook |
    |--------|-----------|-------------------|------------------|
    | SHFE   | Interday  | ✅                | ❌               |
    | SHFE   | Intraday  | ❌                | ✅               |
    | Crypto | Intraday  | ❌                | ✅               |
    | Crypto | Interday  | ❌                | ❌               |

    ContractAwareHook: For interday futures (contract rollover)
    SessionAwareHook: For intraday trading (session context)

Example:
    from echolon.config.markets.factory import MarketFactory

    ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )
    engine = EngineFactory.create_backtest_engine(ctx)
    # or
    engine = EngineFactory.create_deploy_engine(ctx)
"""

from pathlib import Path
from typing import Dict, Any, Optional, Type, TYPE_CHECKING
import logging

from echolon.strategy.frequency.interface import IFrequencyContext, FrequencyType, BarSize
from echolon.markets.interface import IMarketAdapter
from echolon.strategy.frequency.interday_context import InterdayContext
from echolon.strategy.frequency.intraday_context import IntradayContext
from echolon.markets.shfe.adapter import SHFEAdapter
from echolon.markets.crypto.adapter import CryptoAdapter
from echolon.markets.equity.adapter import EquityAdapter
from echolon.data.loaders.contract_loader import ContractIndicatorManager
from echolon.config.markets.core.context import TradingContext

if TYPE_CHECKING:
    from echolon.strategy.interfaces import ITradingEngine

logger = logging.getLogger(__name__)


class EngineFactory:
    """
    Factory for creating trading engines with appropriate adapters.

    Uses TradingContext as the single source of truth for configuration.
    Assembles:
    - Market adapter (SHFE, crypto, etc.)
    - Frequency context (interday, intraday)
    - Trading engine (backtest or deploy)

    Usage:
        from echolon.config.markets.factory import MarketFactory

        ctx = MarketFactory.create(
        market='SHFE', instrument='al', frequency='interday', bar_size='1d',
    )
        engine = EngineFactory.create_backtest_engine(ctx)

        # Or create deploy engine
        engine = EngineFactory.create_deploy_engine(ctx)
    """

    # Registry of market adapters by market code
    MARKET_ADAPTERS: Dict[str, Type[IMarketAdapter]] = {
        "SHFE": SHFEAdapter,
        "CRYPTO": CryptoAdapter,
        "EQUITY": EquityAdapter,
    }

    # Bar size string to enum mapping
    BAR_SIZE_MAP: Dict[str, BarSize] = {
        "1min": BarSize.MINUTE_1,
        "1m": BarSize.MINUTE_1,
        "5min": BarSize.MINUTE_5,
        "5m": BarSize.MINUTE_5,
        "15min": BarSize.MINUTE_15,
        "15m": BarSize.MINUTE_15,
        "30min": BarSize.MINUTE_30,
        "30m": BarSize.MINUTE_30,
        "1h": BarSize.HOUR_1,
        "4h": BarSize.HOUR_4,
        "1d": BarSize.DAILY,
        "1w": BarSize.WEEKLY,
    }

    @classmethod
    def create_market_adapter(
        cls,
        ctx: TradingContext,
        calendar_path: Optional[str] = None,
        mode: str = "backtest",
        market_data_dir: Optional[Path] = None,
    ) -> IMarketAdapter:
        """
        Create market adapter based on TradingContext.

        Args:
            ctx: TradingContext with market and instrument info
            calendar_path: Optional path to trading calendar file (for SHFE)
            mode: "backtest" or "deploy". Both modes use
                  days_before_rollover=1 for SHFE — unified semantics:
                    Hook fires at start of bar T-1 (where T = last trading
                    day before the contract's delivery month). If a position
                    is held, hook submits force-exit and skips strategy.next
                    on T-1. Order fills at the start of trading day T:
                      - backtest: next-bar's open
                      - deploy night-market: 21:00 calendar T-1 night-session
                        open (= trading day T per SHFE convention)
                      - deploy day-only: 14:55 calendar T-1 day-session
                        (one trading day earlier; conservative-safe)
                    Strategy.next resumes normally on bar T.
                  The mode parameter is kept as a seam in case day-only
                  deploy or another execution profile wants different timing
                  in the future without rewiring callers.

        Returns:
            Configured market adapter

        Raises:
            ValueError: If market type is unknown or mode is invalid.
        """
        if mode not in ("backtest", "deploy"):
            raise ValueError(
                f"Unknown mode: {mode!r}. Expected 'backtest' or 'deploy'."
            )

        market = ctx.market_code.upper()
        instrument_code = ctx.instrument_code.lower()

        adapter_class = cls.MARKET_ADAPTERS.get(market)
        if adapter_class is None:
            available = ", ".join(cls.MARKET_ADAPTERS.keys())
            raise ValueError(f"Unknown market: {market}. Available: {available}")

        logger.info(
            f"Creating {market} adapter for instrument: {instrument_code}, mode={mode}"
        )

        # Force-exit timing — both modes signal on T-1 and fill on T's open.
        # T = last trading day of the month before the contract's delivery
        # month (the SHFE rule for "must close by"). Unified semantics.
        days_before_rollover_by_mode = {"backtest": 1, "deploy": 1}

        # Market-specific initialization
        if market == "SHFE":
            return adapter_class(
                symbol=instrument_code,
                trading_calendar_path=calendar_path,
                days_before_rollover=days_before_rollover_by_mode[mode],
                market_data_dir=market_data_dir,
            )
        elif market == "CRYPTO":
            return adapter_class(
                symbol=instrument_code,
            )
        elif market == "EQUITY":
            return adapter_class(symbol=instrument_code, trading_calendar_path=calendar_path)
        else:
            return adapter_class()

    @classmethod
    def create_frequency_context(
        cls,
        ctx: TradingContext,
        market_adapter: Optional[IMarketAdapter] = None
    ) -> IFrequencyContext:
        """
        Create frequency context based on TradingContext.

        Args:
            ctx: TradingContext with frequency and bar_size info
            market_adapter: Optional market adapter for bars_per_day calculation

        Returns:
            Configured frequency context
        """
        freq_str = ctx.frequency
        bar_size_str = ctx.bar_size

        # Determine frequency type
        if freq_str == "interday" or bar_size_str in ("1d", "daily"):
            freq_type = "interday"
        else:
            freq_type = "intraday"

        logger.info(f"Creating {freq_type} frequency context")

        if freq_type == "interday":
            return InterdayContext()

        # Intraday configuration
        bar_size = cls.BAR_SIZE_MAP.get(bar_size_str, BarSize.MINUTE_15)

        # Calculate bars per day from market adapter sessions
        if market_adapter:
            total_minutes = sum(
                s.duration_minutes for s in market_adapter.trading_sessions
            )
            bar_minutes = {
                BarSize.MINUTE_1: 1,
                BarSize.MINUTE_5: 5,
                BarSize.MINUTE_15: 15,
                BarSize.MINUTE_30: 30,
                BarSize.HOUR_1: 60,
                BarSize.HOUR_4: 240,
            }.get(bar_size, 15)
            bars_per_day = total_minutes // bar_minutes
        else:
            # Use ctx.bars_per_day as fallback
            bars_per_day = ctx.bars_per_day

        return IntradayContext(
            bar_size=bar_size,
            bars_per_day=bars_per_day,
            flatten_before_close=True,
            flatten_bars_before_close=0, # exist at last bar of the trading date
        )

    @classmethod
    def create_backtest_engine(
        cls,
        ctx: TradingContext,
        calendar_path: Optional[str] = None,
        indicators_dir: Optional[str] = None,
        strategy_logger_enabled: bool = True,
        strategy_logger_dir: Optional[str] = None,
        market_data_dir: Optional[Path] = None,
    ) -> 'ITradingEngine':
        """
        Create backtest trading engine with appropriate hooks.

        Args:
            ctx: TradingContext (single source of truth)
            calendar_path: Optional path to trading calendar
            indicators_dir: Path to indicators directory (required for futures)
            strategy_logger_enabled: Whether to enable strategy logging
            strategy_logger_dir: Directory for strategy logs

        Returns:
            Configured backtest engine with hooks added based on trading mode

        Hook Composition:
            | Market | Frequency | ContractAwareHook | SessionAwareHook |
            |--------|-----------|-------------------|------------------|
            | SHFE   | Interday  | ✅                | ❌               |
            | SHFE   | Intraday  | ❌                | ✅               |
            | Crypto | Intraday  | ❌                | ✅               |
            | Crypto | Interday  | ❌                | ❌               |

            ContractAwareHook: For interday futures (contract rollover)
            - Adds ContractAwareBroker for accurate PnL across contracts
            - ForcedExitStrategyHook handles forced close via check_contract_expiry()

            SessionAwareHook: For intraday trading (session context)
            - Adds session context provider (SHFE or Crypto specific)
            - Enables VWAP, opening range, session phase tracking
        """
        from echolon.backtest.engine.backtrader_engine import BacktraderEngine   # lazy
        from echolon.backtest.engine.hooks.contract_aware.hook import ContractAwareHook   # lazy
        from echolon.backtest.engine.hooks.session_aware import SessionAwareHook   # lazy

        market_adapter = cls.create_market_adapter(
            ctx, calendar_path, mode="backtest", market_data_dir=market_data_dir
        )
        frequency_context = cls.create_frequency_context(ctx, market_adapter)

        # Determine trading mode
        has_contract_expiry = ctx.has_contract_expiry
        is_interday = frequency_context.frequency_type == FrequencyType.INTERDAY
        is_intraday = frequency_context.frequency_type == FrequencyType.INTRADAY

        # Create base engine with TradingContext
        engine = BacktraderEngine(
            ctx=ctx,
            market_adapter=market_adapter,
            frequency_context=frequency_context,
            strategy_logger_enabled=strategy_logger_enabled,
            strategy_logger_dir=strategy_logger_dir,
        )

        # =====================================================================
        # Hook Composition: Add hooks based on trading mode
        # =====================================================================
        hooks_added = []

        # ContractAwareHook: For interday futures trading
        if has_contract_expiry and is_interday and indicators_dir:
            contract_manager = ContractIndicatorManager(
                indicators_dir=indicators_dir,
                market_adapter=market_adapter
            )
            engine.add_hook(ContractAwareHook(
                market_adapter=market_adapter,
                indicators_dir=indicators_dir,
                contract_manager=contract_manager,
            ))
            hooks_added.append("ContractAwareHook")

        # SessionAwareHook: For intraday trading (provides factual session data)
        if is_intraday:
            bar_size_minutes = cls._get_bar_size_minutes(frequency_context)
            engine.add_hook(SessionAwareHook(
                market_adapter=market_adapter,
                bar_size_minutes=bar_size_minutes,
            ))
            hooks_added.append("SessionAwareHook")

        # Log engine creation
        freq_type = frequency_context.frequency_type.value
        hooks_info = f", hooks=[{', '.join(hooks_added)}]" if hooks_added else ""
        logger.info(
            f"Creating backtest engine: market={market_adapter.market_code}, "
            f"frequency={frequency_context.bar_size.value} ({freq_type}){hooks_info}"
        )

        return engine

    @classmethod
    def _get_bar_size_minutes(cls, frequency_context: IFrequencyContext) -> int:
        """Extract bar size in minutes from frequency context."""
        bar_size_minutes = 5  # Default
        if hasattr(frequency_context, 'bar_size') and hasattr(frequency_context.bar_size, 'minutes'):
            # BarSize enum has a .minutes property
            bar_size_minutes = frequency_context.bar_size.minutes
        return bar_size_minutes

    @classmethod
    def create_deploy_engine(
        cls,
        ctx: TradingContext,
        calendar_path: Optional[str] = None,
        client: Any = None,
        platform: Optional[str] = None,
        market_data_dir: Optional[Path] = None,
        slot_id: Optional[str] = None,
    ) -> 'ITradingEngine':
        """
        Create deployment trading engine.

        Args:
            ctx: TradingContext (single source of truth)
            calendar_path: Optional path to trading calendar
            client: Platform-specific client (e.g., MiniQMTClient)
            platform: Platform name. Only ``'miniqmt'`` is implemented today;
                any other value raises ``ValueError``. Defaults to ``'miniqmt'``.
            slot_id: Deployment slot identifier; forwarded to the engine so that
                per-bar decision logs are written under ``slots/{slot_id}/``.
                Defaults to ``ctx.instrument_code`` when absent.

        Returns:
            Configured deploy engine

        Raises:
            ValueError: If platform is unknown
        """
        platform = platform or "miniqmt"

        market_adapter = cls.create_market_adapter(
            ctx, calendar_path, mode="deploy", market_data_dir=market_data_dir
        )
        frequency_context = cls.create_frequency_context(ctx, market_adapter)

        logger.info(
            f"Creating deploy engine: platform={platform}, "
            f"market={market_adapter.market_code}, "
            f"frequency={frequency_context.bar_size.value}"
        )

        if platform == "miniqmt":
            from echolon.live.platforms.miniqmt.qmt_engine import QMTEngine
            return QMTEngine(
                ctx=ctx,
                market_adapter=market_adapter,
                frequency_context=frequency_context,
                client=client,
                slot_id=slot_id,
            )
        # Only "miniqmt" is implemented today; other broker platforms
        # (e.g. ccxt for crypto live trading) are not yet wired.
        raise ValueError(f"Unknown or unimplemented platform: {platform}")

    @classmethod
    def register_market_adapter(
        cls,
        market_code: str,
        adapter_class: Type[IMarketAdapter]
    ) -> None:
        """
        Register a new market adapter.

        Allows extending the factory with custom market adapters.

        Args:
            market_code: Market identifier (e.g., "CME")
            adapter_class: Market adapter class
        """
        cls.MARKET_ADAPTERS[market_code.upper()] = adapter_class
        logger.info(f"Registered market adapter: {market_code}")

    @classmethod
    def get_available_markets(cls) -> list:
        """Get list of available market codes."""
        return list(cls.MARKET_ADAPTERS.keys())

    @classmethod
    def get_available_bar_sizes(cls) -> list:
        """Get list of available bar size strings."""
        return list(cls.BAR_SIZE_MAP.keys())
