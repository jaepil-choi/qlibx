"""
Contract-Aware Hook
===================

Hook for interday futures trading with contract rollover support.

This hook adds:
1. ContractAwareBroker: Handles position valuation across contract changes
2. Contract price preloading: Optimization for repeated backtests

Force-exit decisions are owned by ForcedExitStrategyHook.check_contract_expiry()
which calls market_adapter.should_rollover() — single source of truth shared
with the deploy path. The ContractExpiryObserver was removed 2026-04-27.

When to use:
- Futures markets with contract expiry (SHFE, CME, etc.)
- Interday trading (positions held overnight)
- NOT needed for intraday (positions flatten at session close)

Usage:
    from .hooks.contract_aware.hook import ContractAwareHook

    hook = ContractAwareHook(
        market_adapter=shfe_adapter,
        indicators_dir='/path/to/indicators',
        contract_manager=manager,  # Optional
    )
    engine.add_hook(hook)
"""

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

import backtrader as bt

from ..base import IEngineHook
from .broker import (
    create_contract_aware_broker,
    preload_contract_prices,
)

if TYPE_CHECKING:
    from ...backtrader_engine import BacktraderEngine
    from echolon.markets.interface import IMarketAdapter
    from echolon.data.loaders.contract_loader import ContractIndicatorManager

logger = logging.getLogger(__name__)


class ContractAwareHook(IEngineHook):
    """
    Hook for interday futures trading with contract awareness.

    Adds contract-aware broker to handle:
    - Position valuation during contract rollovers
    - Accurate PnL calculation across contracts

    Force-exit decisions are owned by ForcedExitStrategyHook (single source of
    truth shared with the deploy path). ContractExpiryObserver was removed
    2026-04-27.

    Parameters:
        market_adapter: Market adapter with contract specifications
        indicators_dir: Path to indicators directory for contract prices
        contract_manager: Optional ContractIndicatorManager for extended features
    """

    def __init__(
        self,
        market_adapter: 'IMarketAdapter',
        indicators_dir: str,
        contract_manager: Optional['ContractIndicatorManager'] = None,
    ):
        self._market_adapter = market_adapter
        self._indicators_dir = indicators_dir
        self._contract_manager = contract_manager

        # Track state
        self._broker_configured = False

    @property
    def name(self) -> str:
        return "ContractAwareHook"

    def on_init(self, engine: 'BacktraderEngine') -> None:
        """
        Early initialization - store contract manager reference.
        """
        # Store contract manager in engine for analyzer access
        if self._contract_manager is not None:
            engine._contract_manager = self._contract_manager

        logger.debug(
            f"[{self.name}] Initialized for {self._market_adapter.market_code}"
        )

    def on_setup(self, cerebro: bt.Cerebro, engine: 'BacktraderEngine') -> None:
        """
        Configure contract-aware broker.
        """
        symbol = engine.get_current_symbol()

        # Pre-load contract prices for optimization performance
        preload_contract_prices(self._indicators_dir)

        # Create contract-aware broker
        contract_broker = create_contract_aware_broker(
            indicators_dir=self._indicators_dir,
            market_adapter=self._market_adapter,
            instrument=symbol,
        )

        # Set initial cash
        contract_broker.setcash(engine._initial_cash)

        # Configure commission from market adapter's contract spec
        # IMPORTANT: Must include mult for futures to calculate P&L correctly
        contract_spec = self._market_adapter.get_contract_spec(symbol)
        if contract_spec is not None:
            if contract_spec.commission_type == "percentage":
                contract_broker.setcommission(
                    commission=contract_spec.commission,
                    mult=contract_spec.multiplier
                )
            else:
                contract_broker.setcommission(
                    commission=contract_spec.commission,
                    commtype=bt.CommInfoBase.COMM_FIXED,
                    mult=contract_spec.multiplier
                )

        # Replace default broker
        cerebro.setbroker(contract_broker)
        self._broker_configured = True

        logger.info(
            f"[{self.name}] ContractAwareBroker configured for {symbol}"
        )

        # NOTE: ContractExpiryObserver was removed (2026-04-27). Force-exit
        # decisions are now owned by ForcedExitStrategyHook.check_contract_expiry()
        # which calls market_adapter.should_rollover() — single source of truth
        # shared with the deploy path.

    def on_post_setup(self, cerebro: bt.Cerebro, engine: 'BacktraderEngine') -> None:
        """
        Post-setup validation.
        """
        if not self._broker_configured:
            logger.warning(f"[{self.name}] Broker was not configured during setup")

    def on_pre_run(self, engine: 'BacktraderEngine') -> None:
        """
        Pre-run validation.
        """
        logger.debug(
            f"[{self.name}] Pre-run check: "
            f"broker={self._broker_configured}"
        )

    def on_post_run(
        self,
        engine: 'BacktraderEngine',
        strategy: bt.Strategy,
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract contract-aware metrics if available.
        """
        # Contract-aware trades are extracted by analyzers, not here
        # This hook just ensures the infrastructure was in place

        results['contract_aware_enabled'] = True
        results['contract_awareness'] = {
            'broker_configured': self._broker_configured,
            'indicators_dir': self._indicators_dir,
        }

        logger.debug(f"[{self.name}] Post-run complete")

        return results

    def __repr__(self) -> str:
        return (
            f"ContractAwareHook("
            f"market={self._market_adapter.market_code}, "
            f"indicators_dir={self._indicators_dir})"
        )
