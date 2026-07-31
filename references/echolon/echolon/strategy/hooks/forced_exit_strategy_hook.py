"""
Forced Exit Strategy Hook
=========================

Hook for interday futures trading with contract expiry handling.

This hook adds forced exit infrastructure to BaseStrategy:
- check_and_process_forced_exits(): Process pending forced exit signals
- signal_forced_exit(): Signal that forced exit is required
- check_contract_expiry(): Check if position needs forced exit

When to use:
- Futures markets with contract expiry (SHFE, CME, etc.)
- Interday trading (positions held overnight)
- NOT needed for intraday (positions flatten at session close)

The hook automatically processes forced exits at the beginning of each bar,
before strategy logic runs. This ensures contract expiry is handled
even if the strategy logic doesn't explicitly check for it.
"""

from datetime import date
from typing import Optional, TYPE_CHECKING, List, Dict, Any
import logging

from .strategy_hook_base import IStrategyHook
from ..interfaces import OrderIntent

if TYPE_CHECKING:
    from ..base import BaseStrategy
    from echolon.markets.interface import IMarketAdapter

logger = logging.getLogger(__name__)


class ForcedExitStrategyHook(IStrategyHook):
    """
    Hook for interday futures trading with forced exit support.

    Adds forced exit infrastructure for handling:
    - Contract expiry (main contract rollover)
    - Market-specific forced close rules

    The hook processes forced exits at the beginning of each bar,
    before strategy logic runs.
    """

    def __init__(self, market_adapter: Optional['IMarketAdapter'] = None):
        """
        Initialize forced exit hook.

        Args:
            market_adapter: Market adapter for contract expiry rules.
                           If None, uses strategy's market_adapter.
        """
        self._market_adapter = market_adapter
        self._strategy: Optional['BaseStrategy'] = None
        self._forced_exit_signal: Optional[dict] = None
        self._forced_exits: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "ForcedExitStrategyHook"

    def on_init(self, strategy: 'BaseStrategy') -> None:
        """
        Inject forced exit methods into strategy instance.
        """
        self._strategy = strategy

        # Use strategy's market adapter if not provided
        if self._market_adapter is None:
            self._market_adapter = strategy.market_adapter

        # Inject forced exit methods as bound methods
        strategy.check_and_process_forced_exits = self.check_and_process_forced_exits
        strategy.signal_forced_exit = self.signal_forced_exit
        strategy.check_contract_expiry = self.check_contract_expiry
        strategy._has_forced_exit_signal = self._has_forced_exit_signal

        # Initialize forced exit state
        strategy._forced_exit_signal = None

        logger.debug(f"[{self.name}] Forced exit infrastructure injected")

    def on_start(self, strategy: 'BaseStrategy') -> None:
        """No action needed on start."""
        pass

    def on_bar_start(self, strategy: 'BaseStrategy') -> bool:
        """
        Check contract expiry and process forced exits BEFORE strategy logic.

        Single source of truth: check_contract_expiry() runs every bar in both
        backtest and deploy. It calls market_adapter.should_rollover() and
        sets the signal if true.

        Returns:
            True to continue processing, False if forced exit was submitted
            this bar (strategy.next is then skipped).
        """
        # Check contract expiry if no signal pending yet
        if not self._has_forced_exit_signal():
            self.check_contract_expiry()

        if self._has_forced_exit_signal():
            processed = self._process_forced_exit_signals()
            if processed:
                return False  # Skip rest of bar
        return True  # Continue processing

    def on_bar_end(self, strategy: 'BaseStrategy') -> None:
        """No action needed on bar end."""
        pass

    def on_stop(self, strategy: 'BaseStrategy') -> None:
        """Clear any pending signals on stop."""
        self._forced_exit_signal = None

    # =========================================================================
    # Forced Exit Methods (injected into strategy)
    # =========================================================================

    def check_and_process_forced_exits(self) -> bool:
        """
        Check for and process any pending forced exit signals.

        Call this at the beginning of on_bar() to ensure forced exits
        are processed before strategy logic.

        Returns:
            True if forced exit was processed, False otherwise
        """
        if not self._has_forced_exit_signal():
            return False

        return self._process_forced_exit_signals()

    def _process_forced_exit_signals(self) -> bool:
        """Process forced exit signals from contract expiry check."""
        signal = self._forced_exit_signal

        if not signal or not signal.get('required', False):
            return False

        current_position_size = self._strategy.get_position_size()
        signal_position_size = signal.get('position_size', 0)
        contract_code = signal.get('contract_code', 'unknown')
        observer_date = signal.get('observer_date', 'unknown')
        current_dt = self._strategy.get_current_datetime()

        if current_position_size == 0:
            logger.warning(
                f"[FORCED_EXIT] Position closed by exit rule before forced exit | "
                f"signal_snapshot={signal_position_size}, contract={contract_code}, "
                f"signal_date={observer_date}, process_date={current_dt.date()}"
            )
            self._forced_exit_signal = None
            if hasattr(self._strategy, 'exit_rule'):
                exit_rule = self._strategy.exit_rule
                if hasattr(exit_rule, '_reset_position_state'):
                    exit_rule._reset_position_state()
            return True

        if abs(current_position_size) != abs(signal_position_size):
            logger.warning(
                f"[FORCED_EXIT] Position partially closed before forced exit | "
                f"current_pos={current_position_size}, signal_snapshot={signal_position_size}"
            )

        current_price = self._strategy.get_current_price()
        reason = signal.get('reason', 'Contract expiry forced exit')

        self._strategy.log(
            f"EXECUTING FORCED EXIT: {reason} - Contract: {contract_code}, "
            f"Size: {current_position_size}, Price: {current_price:.2f}"
        )

        exit_size = abs(current_position_size)

        if self._strategy.is_long_position():
            intent = OrderIntent.EXIT_LONG
        else:
            intent = OrderIntent.EXIT_SHORT

        result = self._strategy.exit(intent=intent, size=exit_size)

        if result.status.name in ['SUBMITTED', 'ACCEPTED']:
            strategy_logger = self._strategy.strategy_logger
            if strategy_logger and hasattr(strategy_logger, 'log_order_event'):
                forced_exit_order_data = {
                    'action': 'submit',
                    'side': intent.value,
                    'size': exit_size,
                    'status': result.status.value,
                    'order_id': result.order_id,
                    'is_forced_exit': True,
                    'forced_exit_reason': reason,
                    'datetime': self._strategy.get_current_datetime().isoformat()
                }
                strategy_logger.log_order_event(forced_exit_order_data)

            self._strategy.log(
                f"Forced exit order submitted: {intent.value} {exit_size} at {current_price:.2f}"
            )

            self._forced_exits.append({
                'date': self._strategy.get_current_datetime().isoformat(),
                'contract_code': contract_code,
                'position_size': signal_position_size,
                'close_price': float(current_price),
                'reason': reason,
                'status': 'submitted',
            })

            self._notify_components_of_forced_exit(signal)
            self._forced_exit_signal = None
            return True
        else:
            self._strategy.log(f"Forced exit order failed: {result.message}", "error")
            return False

    def _has_forced_exit_signal(self) -> bool:
        """Check if there is a pending forced exit signal."""
        return (
            self._forced_exit_signal is not None and
            self._forced_exit_signal.get('required', False)
        )

    def _notify_components_of_forced_exit(self, signal: dict) -> None:
        """Notify relevant components about forced exit."""
        if hasattr(self._strategy, 'exit_rule'):
            exit_rule = self._strategy.exit_rule
            if hasattr(exit_rule, 'clear_position_info'):
                exit_rule.clear_position_info()
                self._strategy.log("Notified exit component of forced exit - position state cleared")
            elif hasattr(exit_rule, '_reset_position_state'):
                exit_rule._reset_position_state()
                self._strategy.log("Notified exit component of forced exit - position state reset")

    def signal_forced_exit(
        self,
        reason: str,
        contract_code: str = "",
        position_size: Optional[float] = None,
        observer_date: Optional[date] = None
    ) -> None:
        """
        Signal that a forced exit is required.

        Called internally by `check_contract_expiry()` or by adapters that signal expiry events.

        Args:
            reason: Reason for forced exit (e.g., "Contract expiry")
            contract_code: Contract code being exited
            position_size: Position size at time of signal (defaults to current)
            observer_date: Date when signal was generated
        """
        if position_size is None:
            position_size = self._strategy.get_position_size()

        if observer_date is None:
            observer_date = self._strategy.get_current_datetime().date()

        self._forced_exit_signal = {
            'required': True,
            'reason': reason,
            'contract_code': contract_code,
            'position_size': position_size,
            'observer_date': str(observer_date),
        }
        self._strategy.log(f"Forced exit signaled: {reason} for contract {contract_code}")

    def check_contract_expiry(self) -> bool:
        """
        Check if current position needs forced exit due to contract expiry.

        Uses the market_adapter to check expiry rules.

        Returns:
            True if forced exit signal was set, False otherwise
        """
        # Skip if no position
        if not self._strategy.has_position():
            return False

        # Skip if no market adapter
        adapter = self._market_adapter
        if adapter is None:
            return False

        # Skip if market doesn't have contract expiry
        if not hasattr(adapter, 'has_contract_expiry') or not adapter.has_contract_expiry:
            return False

        # Get current date and position
        current_date = self._strategy.get_current_datetime().date()
        position_size = self._strategy.get_position_size()

        # Resolve the contract this position is HELD on (not today's main
        # contract). Once the front-month rolls over the strategy may still
        # hold the previous month, and that's the contract whose expiry
        # drives the force-exit timing. Falls back to today's main contract
        # only if the portfolio cannot expose the held contract.
        held_contract: Optional[str] = None
        portfolio = getattr(self._strategy, 'portfolio', None)
        if portfolio is not None and hasattr(portfolio, 'get_position_contract'):
            held_contract = portfolio.get_position_contract()
        if not held_contract and hasattr(adapter, 'get_main_contract'):
            held_contract = adapter.get_main_contract(current_date)
        if not held_contract:
            return False

        # Check if should rollover/exit (uses adapter's rollover logic)
        if hasattr(adapter, 'should_rollover'):
            should_exit = adapter.should_rollover(
                held_contract, current_date, abs(int(position_size))
            )
            if should_exit:
                self.signal_forced_exit(
                    reason="Contract expiry - position must close",
                    contract_code=held_contract,
                    position_size=position_size,
                    observer_date=current_date
                )
                return True

        return False

    def get_forced_exits(self) -> List[Dict[str, Any]]:
        """Return list of all forced exits this hook has executed (analytics).

        Each entry is a dict with: date (ISO), contract_code, position_size,
        close_price, reason, status. Returned list is a shallow copy.
        """
        return list(self._forced_exits)

    def __repr__(self) -> str:
        market = self._market_adapter.market_code if self._market_adapter else 'None'
        return f"ForcedExitStrategyHook(market={market})"
