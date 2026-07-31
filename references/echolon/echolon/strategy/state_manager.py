"""
State Manager
=============

Handles state persistence for live trading continuity.

Responsibilities:
- Save strategy state to disk (positions, stops, counters)
- Load strategy state on restart
- Ensure consistent state across trading sessions
- Handle state versioning and migration

State includes:
- Current position information
- Trailing stop levels
- Bars in position counter
- Daily trade counters
- Risk circuit breaker states
- Last processed bar timestamp

This enables the deploy engine to resume from where it left off
after restarts, maintaining accurate position tracking and risk limits.

Example:
    state_manager = StateManager(state_path="data/strategy_state.json")
    state = state_manager.load_state()
    # ... trading session ...
    state_manager.save_state(current_state)
"""

import json
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field


@dataclass
class PendingExitIntent:
    """An EXIT-class order intent that hasn't fully resolved.

    Set by the runner when an EXIT-class order is first submitted and
    cleared when the corresponding handle reaches TERMINAL_FILLED with
    full fill. Persists across cycles via strategy_state.json — the
    recovery hook in TradingSlot.execute_bar reads this on next bar and
    re-fires the exit before the strategy's normal on_bar runs.

    Reference: design doc Amendment B (sections 20.4 + 21.10).
    """
    intent: str                          # 'EXIT_LONG' | 'EXIT_SHORT' | 'ROLLOVER_CLOSE' | 'FORCED_EXIT'
    original_size: int
    remaining_size: int
    attempts_so_far: int
    original_decision_time: str          # ISO datetime of the original deciding bar
    last_attempt_time: str               # ISO datetime of most recent attempt
    cycles_pending: int = 1


@dataclass
class StrategyState:
    """
    Strategy state for persistence.

    Contains all state that needs to survive restarts.
    """
    # Version for state migration
    version: str = "1.1"

    # Position state
    position_symbol: Optional[str] = None
    position_size: float = 0.0
    position_side: str = "FLAT"  # LONG, SHORT, FLAT
    position_entry_price: float = 0.0
    position_entry_datetime: Optional[str] = None

    # Exit management state
    trailing_stop_price: Optional[float] = None
    bars_in_position: int = 0
    entry_mode: Optional[str] = None  # SNIPER, MACHINE_GUN

    # Risk management state
    daily_trades_count: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    circuit_breaker_active: bool = False
    last_trade_bar: int = 0

    # Timing state
    last_processed_datetime: Optional[str] = None
    last_trading_date: Optional[str] = None

    # Pending EXIT intent — survives across cycles for ABANDONED-EXIT recovery (Amendment B).
    pending_exit_intent: Optional[PendingExitIntent] = None

    # Custom state (for strategy-specific data)
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyState':
        """Create from dictionary."""
        # Handle version migration if needed
        version = data.get("version", "1.0")
        if version not in ("1.0", "1.1"):
            data = cls._migrate_state(data, version)

        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        # Rehydrate nested PendingExitIntent if present.
        pending = filtered_data.get("pending_exit_intent")
        if isinstance(pending, dict):
            filtered_data["pending_exit_intent"] = PendingExitIntent(**pending)

        return cls(**filtered_data)

    @staticmethod
    def _migrate_state(data: Dict[str, Any], from_version: str) -> Dict[str, Any]:
        """
        Migrate state from older versions.

        Args:
            data: State data
            from_version: Version to migrate from

        Returns:
            Migrated state data
        """
        # Add migration logic as versions evolve
        # For now, just return data as-is
        return data


class StateManager:
    """
    Manages strategy state persistence.

    Saves and loads state to/from JSON files for session continuity.
    """

    def __init__(self, state_path: str):
        """
        Initialize state manager.

        Args:
            state_path: Path to state file. Required — caller chooses the
                location. Both echolon callers (BaseStrategy in
                ``strategy/base.py`` and the live ``TradingSlot``) pass it
                explicitly.
        """
        self._state_path = Path(state_path)
        self._state: Optional[StrategyState] = None

    @property
    def state_path(self) -> Path:
        """Get state file path."""
        return self._state_path

    def load_state(self) -> StrategyState:
        """
        Load state from file.

        Returns:
            Loaded state or new empty state if file doesn't exist
        """
        if not self._state_path.exists():
            self._state = StrategyState()
            return self._state

        with open(self._state_path, 'r') as f:
            data = json.load(f)

        self._state = StrategyState.from_dict(data)
        return self._state

    def save_state(self, state: StrategyState = None) -> None:
        """
        Save state to file.

        Args:
            state: State to save (uses internal state if None)
        """
        if state is not None:
            self._state = state

        if self._state is None:
            return

        # Ensure directory exists (also done inside write_state_atomically, harmless)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)

        from echolon._internal.atomic_state import write_state_atomically
        write_state_atomically(str(self._state_path), self._state.to_dict())

    def clear_state(self) -> None:
        """Clear state file and internal state."""
        self._state = StrategyState()
        if self._state_path.exists():
            self._state_path.unlink()

    def get_state(self) -> Optional[StrategyState]:
        """Get current state (load if not loaded)."""
        if self._state is None:
            self.load_state()
        return self._state

    def update_position(
        self,
        symbol: str,
        size: float,
        side: str,
        entry_price: float,
        entry_datetime: datetime = None
    ) -> None:
        """
        Update position state.

        Args:
            symbol: Position symbol
            size: Position size
            side: Position side (LONG, SHORT, FLAT)
            entry_price: Entry price
            entry_datetime: Entry datetime
        """
        state = self.get_state()
        state.position_symbol = symbol
        state.position_size = size
        state.position_side = side
        state.position_entry_price = entry_price
        state.position_entry_datetime = (
            entry_datetime.isoformat() if entry_datetime else None
        )
        state.bars_in_position = 0

    def clear_position(self) -> None:
        """Clear position state."""
        state = self.get_state()
        state.position_symbol = None
        state.position_size = 0.0
        state.position_side = "FLAT"
        state.position_entry_price = 0.0
        state.position_entry_datetime = None
        state.trailing_stop_price = None
        state.bars_in_position = 0
        state.entry_mode = None

    def update_trailing_stop(self, stop_price: float) -> None:
        """Update trailing stop price."""
        state = self.get_state()
        state.trailing_stop_price = stop_price

    def increment_bars_in_position(self) -> int:
        """
        Increment bars in position counter.

        Returns:
            New bars in position count
        """
        state = self.get_state()
        state.bars_in_position += 1
        return state.bars_in_position

    def update_daily_stats(self, trade_pnl: float = None, is_win: bool = None) -> None:
        """
        Update daily trading statistics.

        Args:
            trade_pnl: P&L from a trade (if trade occurred)
            is_win: Whether trade was profitable
        """
        state = self.get_state()
        state.daily_trades_count += 1

        if trade_pnl is not None:
            state.daily_pnl += trade_pnl

        if is_win is not None:
            if is_win:
                state.consecutive_losses = 0
            else:
                state.consecutive_losses += 1

    def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at start of new day)."""
        state = self.get_state()
        state.daily_trades_count = 0
        state.daily_pnl = 0.0
        state.last_trading_date = datetime.now().date().isoformat()

    def set_circuit_breaker(self, active: bool) -> None:
        """Set circuit breaker state."""
        state = self.get_state()
        state.circuit_breaker_active = active

    def update_last_processed(self, dt: datetime) -> None:
        """Update last processed datetime."""
        state = self.get_state()
        state.last_processed_datetime = dt.isoformat()

    def set_custom(self, key: str, value: Any) -> None:
        """Set custom state value."""
        state = self.get_state()
        state.custom[key] = value

    def get_custom(self, key: str, default: Any = None) -> Any:
        """Get custom state value."""
        state = self.get_state()
        return state.custom.get(key, default)

    # ------------------------------------------------------------------
    # ABANDONED-EXIT recovery (Amendment B)
    # ------------------------------------------------------------------

    def set_pending_exit_intent(self, pending: PendingExitIntent) -> None:
        """Record an unresolved EXIT-class order intent.

        Called by the runner when an EXIT-class order is first submitted
        and again when it's still unfilled at end-of-cycle (incrementing
        ``cycles_pending``). Persisted on next save_state().
        """
        state = self.get_state()
        state.pending_exit_intent = pending

    def clear_pending_exit_intent(self) -> None:
        """Mark the pending exit fully resolved (e.g. TERMINAL_FILLED)."""
        state = self.get_state()
        state.pending_exit_intent = None

    def get_pending_exit_intent(self) -> Optional[PendingExitIntent]:
        state = self.get_state()
        return state.pending_exit_intent
