# BaseStrategy Class Reference

## Overview

`BaseStrategy` is the foundation class for all platform-agnostic strategies, providing universal infrastructure for component coordination, state persistence, and lifecycle management.

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    PLATFORM LAYER                               │
│  Backtrader Platform    │    MiniQMT Platform                   │
│  • BacktraderTradingEngine  • QMTTradingEngine                  │
├─────────────────────────────────────────────────────────────────┤
│             PLATFORM-AGNOSTIC STRATEGY LAYER                    │
│  Strategy Components (Pure Trading Logic)                       │
│  • entry.py  • exit.py  • risk.py  • sizer.py                  │
│  • strategy.py (main coordinator)                               │
├─────────────────────────────────────────────────────────────────┤
│                  ABSTRACTION LAYER                              │
│  Core Interfaces & Base Classes                                 │
│  • ITradingEngine  • BaseStrategy  • BaseComponent              │
│  • IMarketData     • IPortfolio    • IOrderManager              │
└─────────────────────────────────────────────────────────────────┘
```

## Class Definition

```python
class BaseStrategy(IStrategyCallbacks):
    """Platform-agnostic base strategy class with universal infrastructure."""

    def __init__(self, trading_engine: ITradingEngine, **params):
        """Initialize with automatic component setup."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LIFECYCLE METHODS - TEMPLATE METHOD PATTERN
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #
    # CRITICAL: Do NOT override on_start() or on_bar() directly!
    # Override the underscore-prefixed hooks instead:
    #   - _on_strategy_start() for custom startup logic
    #   - _execute_bar() for bar-by-bar trading logic

    def on_start(self) -> None:
        """
        Called when strategy starts - TEMPLATE METHOD.

        IMPORTANT: Do NOT override this method directly in strategy.py.
        Override _on_strategy_start() instead for custom startup logic.

        The on_start() method orchestrates:
        1. Component setup via setup_components()
        2. Component validation
        3. Hook on_start() callbacks
        4. Your _on_strategy_start() implementation
        """

    def _on_strategy_start(self) -> None:
        """
        Override this method for custom startup logic.

        Called AFTER all components and hooks are initialized.

        Example in strategy.py:
            def _on_strategy_start(self):
                self.log("Custom strategy initialization")
                self.log(f"Using RSI period: {self.params['rsi_period']}")
        """

    def on_bar(self) -> None:
        """
        Called on each new bar - TEMPLATE METHOD.

        IMPORTANT: Do NOT override this method directly in strategy.py.
        Override _execute_bar() instead to implement your trading logic.

        The on_bar() method orchestrates:
        1. Hook on_bar_start() callbacks
        2. Your _execute_bar() implementation
        3. Hook on_bar_end() callbacks

        For SHFE interday: Forced exits are processed BEFORE _execute_bar().
        For intraday: Session context is updated before _execute_bar().
        """

    def _execute_bar(self) -> None:
        """
        Override this method to implement your trading logic.

        This is where you should:
        - Check risk constraints
        - Generate entry signals
        - Manage exits

        Example in strategy.py:
            def _execute_bar(self):
                risk_output = self.risk_manager.can_trade()
                if not risk_output.trading_allowed:
                    return
                # ... rest of trading logic
        """

    def on_stop(self) -> None:
        """Called when strategy stops."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # HELPER METHODS (Available to use)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def get_indicator(self, name: str, index: int = 0) -> float:
        """Get indicator value (see Three-Tier Indicator System)."""

    def get_market_regime(self, index: int = 0) -> str:
        """INTERDAY ONLY: Get market regime ('trending_up', 'ranging', etc.)."""

    def get_session_phase(self, index: int = 0) -> str:
        """INTRADAY ONLY: Get session phase (names vary by bar size - see TradingContext.tradeable_phases)."""

    def get_position(self) -> Optional[Position]:
        """Get the current position."""

    def has_position(self) -> bool:
        """Check if there is an open position."""

    def has_pending_orders(self) -> bool:
        """
        CRITICAL: Check if there are pending orders awaiting execution.

        Must check this before submitting new orders (especially for intraday).
        Backtrader market orders execute at NEXT bar's open, not immediately.
        Without this guard, consecutive bars with entry signals will submit
        multiple orders, resulting in massive unintended positions.
        """

    def is_long_position(self) -> bool:
        """Check if current position is long."""

    def entry(self, intent: OrderIntent, size: float, price: float = None) -> OrderResult:
        """Submit an entry order."""

    def exit(self, intent: OrderIntent = None, size: float = None, price: float = None) -> OrderResult:
        """Submit an exit order."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # UNIVERSAL INFRASTRUCTURE (Automatic)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def setup_components(self) -> bool:
        """Universal component setup - automatically detects and initializes."""

    def save_state(self, state_dir: str) -> bool:
        """Save strategy and component states for live trading persistence."""

    def restore_state(self, state_dir: str) -> bool:
        """Restore strategy and component states from persistence files."""

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # HOOK-INJECTED METHODS (Only available in specific configurations)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # NOTE: The following method is ONLY available when ForcedExitStrategyHook
    # is applied (SHFE futures with interday frequency). It is NOT available
    # for intraday or crypto strategies.

    def check_and_process_forced_exits(self) -> bool:
        """
        HOOK-INJECTED (ForcedExitStrategyHook only):
        INTERNAL USE ONLY - Called by BacktraderStrategyBridge.next()
        DO NOT call in strategy.on_bar() - handled by infrastructure.

        Only available for: SHFE + interday frequency
        """
```

## Universal Infrastructure

The following is handled **automatically** by BaseStrategy:

| Feature | Description |
|---------|-------------|
| **Component Setup** | Detects and initializes entry_rule, exit_rule, risk_manager, position_sizer |
| **State Persistence** | Automatic save/restore for live trading deployments |
| **Forced Exit Handling** | SHFE contract expiry exits processed before `on_bar()` |
| **Logging Integration** | Strategy logger automatically connected |

## Strategy Implementation Pattern

```python
from echolon.strategy.base import BaseStrategy
from echolon.strategy.interfaces import ITradingEngine, OrderIntent

class strategy_main(BaseStrategy):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Components automatically set up by universal infrastructure

    def _on_strategy_start(self):
        """Called AFTER components and hooks are initialized.

        Override this, NOT ``on_start()``. ``BaseStrategy.on_start()`` is a
        Template Method that orchestrates component setup + validation +
        hook callbacks (echolon/strategy/base.py:890).
        """
        self.log("Strategy starting...")

    def _execute_bar(self):
        """
        Override _execute_bar() (NOT on_bar()) for trading logic.

        The on_bar() template method handles:
        - Hook lifecycle (on_bar_start, on_bar_end)
        - Forced exits for interday futures
        - Session context updates for intraday
        """
        # 1. Check risk constraints
        risk_output = self.risk_manager.can_trade()

        # CRITICAL: Handle trading_allowed=False carefully!
        # - Circuit breakers (drawdown/session loss): Flatten + halt
        # - Position limits: Block entries BUT still allow exit evaluation
        if not risk_output.trading_allowed:
            if self.has_position():
                # drawdown_halt_triggered / session_halt_triggered are
                # STRATEGY-AUTHOR EXTRAS on RiskOutput — not declared on
                # the base schema. They arrive via extra='allow'. Use
                # getattr() so the code doesn't AttributeError when a
                # generic risk.py only returns the required fields.
                if getattr(risk_output, 'drawdown_halt_triggered', False) \
                        or getattr(risk_output, 'session_halt_triggered', False):
                    self.exit()  # Flatten position
                    return  # Halt all activity
                # Position limit? Fall through to exit logic (don't return!)
            else:
                # No position and trading blocked - nothing to do
                return

        # 2. Entry Logic (if trading allowed AND no position AND no pending orders)
        # CRITICAL: Must check has_pending_orders() for intraday strategies!
        # Backtrader orders execute at NEXT bar's open, not immediately.
        if risk_output.trading_allowed and not self.has_position() and not self.has_pending_orders():
            entry_signal = self.entry_rule.generate_signal()
            if entry_signal.signal != 'HOLD':
                sizer_output = self.position_sizer.calculate_size(entry_signal)
                if sizer_output.calculated_size > 0:
                    self.entry(entry_signal.intent, sizer_output.calculated_size)

        # 3. Exit Logic (if has position AND no pending orders)
        # NOTE: This evaluates even when trading_allowed=False (e.g., position limit)
        # Exit rules MUST still run to allow positions to close!
        elif self.has_position() and not self.has_pending_orders():
            exit_decision = self.exit_rule.should_exit()
            if exit_decision.should_exit:
                self.exit(exit_decision.intent)

    def on_stop(self):
        """Called when strategy stops."""
        self.log("Strategy stopped.")
```

## Component Coordination

All component methods return BaseModel instances. Use **attribute access**:

```python
# CORRECT: Attribute access
if entry_signal.signal != 'HOLD':
    size = sizer_output.calculated_size
    self.entry(entry_signal.intent, size)

# WRONG: Dict access
if entry_signal['signal'] != 'HOLD':  # TypeError!
```

## Key Benefits

- **Automatic Component Setup**: No manual initialization required
- **State Persistence**: Automatic save/restore for live trading
- **Forced Exit Handling**: Contract expiry processed automatically
- **Simplified Implementation**: Focus on business logic only
