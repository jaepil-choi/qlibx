"""
Slot-Aware Portfolio
====================

Per-slot portfolio with virtual position tracking.

Implements IPortfolio so BaseStrategy works unchanged.
Position data comes from internal tracking (updated via fill callbacks),
NOT from QMT queries. This isolates each slot's position from the
shared brokerage account.

Thread safety: open_position, close_position, update_mark_to_market
are called from the main thread ONLY (PortfolioTradingRunner phases
are sequential).
"""

import logging
from typing import Any, Dict, List, Optional

from echolon.strategy.interfaces import (
    IMarketData,
    IPortfolio,
    Position,
    AccountInfo,
)
from .capital_slot import CapitalSlot

logger = logging.getLogger(__name__)


class SlotAwarePortfolio(IPortfolio):
    """
    Per-slot portfolio backed by a VirtualPosition and CapitalSlot.

    The strategy sees this as a normal IPortfolio. Position state is
    entirely local — never reads from QMT.
    """

    def __init__(
        self,
        market_data: IMarketData,
        capital_slot: CapitalSlot,
        multiplier: int,
        margin_rate: float,
    ):
        """
        Args:
            market_data: IMarketData for current price lookups
            capital_slot: Capital tracking for this slot
            multiplier: Contract multiplier (e.g., 5 for al, 5 for cu)
            margin_rate: Margin rate (e.g., 0.12 for 12%)
        """
        self._market_data = market_data
        self._capital = capital_slot
        self._multiplier = multiplier
        self._margin_rate = margin_rate

        # Virtual position
        self._position: Optional[Position] = None

    def set_client(self, client) -> None:
        """No-op. SlotAwarePortfolio tracks positions locally, not via QMT."""
        pass

    # =========================================================================
    # IPortfolio interface
    # =========================================================================

    def get_total_value(self) -> float:
        """Total portfolio value = slot equity."""
        return self._capital.equity

    def get_cash(self) -> float:
        """Available cash = equity - margin."""
        return self._capital.available_cash

    def get_position(self, symbol: Optional[str] = None) -> Optional[Position]:
        """Get current virtual position."""
        return self._position

    def get_all_positions(self) -> List[Position]:
        """Get all positions (zero or one)."""
        if self._position is not None and self._position.size > 0:
            return [self._position]
        return []

    def get_realized_pnl(self) -> float:
        """Total realized P&L from capital slot."""
        return self._capital.realized_pnl

    def get_unrealized_pnl(self) -> float:
        """Unrealized P&L from capital slot (recomputed each bar)."""
        return self._capital.unrealized_pnl

    def has_position(self, symbol: Optional[str] = None) -> bool:
        """Check if there's an open position."""
        return self._position is not None and self._position.size > 0

    def get_position_size(self, symbol: Optional[str] = None) -> float:
        """Get signed position size."""
        if self._position is None:
            return 0.0
        if self._position.direction == "SHORT":
            return -abs(self._position.size)
        return self._position.size

    def get_position_value(self, symbol: Optional[str] = None) -> float:
        """Get position notional value including multiplier."""
        if self._position is None:
            return 0.0
        price = self._market_data.get_current_price()
        return self._position.size * price * self._multiplier

    def get_account_info(self) -> AccountInfo:
        """Get account information."""
        return AccountInfo(
            equity=self.get_total_value(),
            cash=self.get_cash(),
            margin_used=self._capital.margin_used,
            margin_available=self.get_cash(),
            unrealized_pnl=self.get_unrealized_pnl(),
            realized_pnl=self.get_realized_pnl(),
            currency="CNY",
        )

    # =========================================================================
    # Mark-to-market
    # =========================================================================

    def update_mark_to_market(self, current_price: float) -> None:
        """
        Recompute unrealized P&L and margin from VP + current price.

        Called once per bar BEFORE strategy.on_bar().
        Updates capital_slot.unrealized_pnl, capital_slot.margin_used,
        and peak_equity.
        """
        if self._position is None or self._position.size == 0:
            self._capital.unrealized_pnl = 0.0
            self._capital.margin_used = 0.0
        else:
            size = self._position.size
            avg_price = self._position.avg_price
            direction = self._position.direction

            if direction == "LONG":
                raw_pnl = (current_price - avg_price) * size * self._multiplier
            else:  # SHORT
                raw_pnl = (avg_price - current_price) * size * self._multiplier

            self._capital.unrealized_pnl = raw_pnl
            self._capital.margin_used = (
                current_price * size * self._multiplier * self._margin_rate
            )

            # Update position object
            self._position.unrealized_pnl = raw_pnl
            self._position.current_price = current_price
            self._position.market_value = current_price * size * self._multiplier

        # Update peak after mark-to-market
        current_eq = self._capital.equity
        if current_eq > self._capital.peak_equity:
            self._capital.peak_equity = current_eq

    # =========================================================================
    # Position management (called during fill processing)
    # =========================================================================

    def open_position(
        self,
        symbol: str,
        direction: str,
        size: float,
        price: float,
    ) -> None:
        """
        Open or scale into a position.

        For fresh entry: creates new VP.
        For scale-in: weighted average price.
        Rejects direction mismatch (must close first).
        """
        if price <= 0:
            raise ValueError(
                f"[{self._capital.slot_id}] open_position rejected: price={price} "
                f"(must be > 0). Fill price may be missing from callback."
            )

        if self._position is not None and self._position.size > 0:
            # Scale-in: same direction only
            if self._position.direction != direction:
                raise ValueError(
                    f"Direction mismatch: existing={self._position.direction}, "
                    f"new={direction}. Close existing position first."
                )
            # Weighted average
            old_size = self._position.size
            old_price = self._position.avg_price
            new_size = old_size + size
            new_avg = (old_price * old_size + price * size) / new_size

            self._position.size = new_size
            self._position.avg_price = new_avg
            self._position.market_value = price * new_size * self._multiplier

            logger.info(
                f"[{self._capital.slot_id}] Scale-in: {direction} "
                f"{old_size}->{new_size} @ avg {new_avg:.2f}"
            )
        else:
            # Fresh entry
            self._position = Position(
                symbol=symbol,
                size=size,
                avg_price=price,
                market_value=price * size * self._multiplier,
                unrealized_pnl=0.0,
                realized_pnl=self._capital.realized_pnl,
                direction=direction,
                current_price=price,
            )
            logger.info(
                f"[{self._capital.slot_id}] Open: {direction} "
                f"{size} @ {price:.2f}"
            )

        # Update capital slot position tracking
        self._capital.prev_position_size = self._position.size
        self._capital.prev_avg_price = self._position.avg_price

    def close_position(self, size: float, price: float) -> float:
        """
        Close (full or partial) position.

        Returns realized P&L for the closed portion.
        Does NOT reset unrealized — that happens in update_mark_to_market().
        """
        if self._position is None or self._position.size == 0:
            raise ValueError("No position to close")

        if price <= 0:
            raise ValueError(
                f"[{self._capital.slot_id}] close_position rejected: price={price} "
                f"(must be > 0). Fill price may be missing from callback."
            )

        close_size = min(size, self._position.size)
        avg_price = self._position.avg_price
        direction = self._position.direction

        # Calculate realized P&L for closed portion
        if direction == "LONG":
            realized = (price - avg_price) * close_size * self._multiplier
        else:  # SHORT
            realized = (avg_price - price) * close_size * self._multiplier

        remaining = self._position.size - close_size

        if remaining <= 0:
            # Full close — clear unrealized before recording trade
            # so peak_equity is not inflated by double-counting
            self._capital.unrealized_pnl = 0.0
            self._capital.margin_used = 0.0
            logger.info(
                f"[{self._capital.slot_id}] Full close: {direction} "
                f"{close_size} @ {price:.2f}, realized={realized:.2f}"
            )
            self._position = None
            self._capital.prev_position_size = 0.0
            self._capital.prev_avg_price = 0.0
        else:
            # Partial close — avg_price unchanged, update unrealized for remaining
            self._position.size = remaining
            self._position.market_value = price * remaining * self._multiplier
            self._capital.prev_position_size = remaining
            # Recompute unrealized for remaining position so peak is not inflated
            if direction == "LONG":
                self._capital.unrealized_pnl = (price - avg_price) * remaining * self._multiplier
            else:
                self._capital.unrealized_pnl = (avg_price - price) * remaining * self._multiplier
            self._capital.margin_used = price * remaining * self._multiplier * self._margin_rate
            logger.info(
                f"[{self._capital.slot_id}] Partial close: {close_size}/{close_size + remaining} "
                f"@ {price:.2f}, realized={realized:.2f}"
            )

        # Record realized P&L in capital slot
        self._capital.record_trade(realized)

        return realized

    # =========================================================================
    # State persistence
    # =========================================================================

    def save_state(self) -> Dict[str, Any]:
        """
        Serialize VP state for strategy_state.json.

        Returns position_* fields matching StrategyState format.
        """
        if self._position is not None and self._position.size > 0:
            return {
                'position_symbol': self._position.symbol,
                'position_size': self._position.size,
                'position_side': self._position.direction,
                'position_entry_price': self._position.avg_price,
            }
        return {
            'position_symbol': None,
            'position_size': 0.0,
            'position_side': 'FLAT',
            'position_entry_price': 0.0,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """
        Restore VP from strategy_state.json position_* fields.

        If there was a position, recreate it.
        """
        size = state.get('position_size', 0.0)
        side = state.get('position_side', 'FLAT')

        if size > 0 and side != 'FLAT':
            symbol = state.get('position_symbol', '')
            entry_price = state.get('position_entry_price', 0.0)
            self._position = Position(
                symbol=symbol,
                size=size,
                avg_price=entry_price,
                market_value=0.0,  # Will be recomputed by mark-to-market
                unrealized_pnl=0.0,
                realized_pnl=self._capital.realized_pnl,
                direction=side,
                current_price=entry_price,
            )
            self._capital.prev_position_size = size
            self._capital.prev_avg_price = entry_price
            logger.info(
                f"[{self._capital.slot_id}] Position restored: "
                f"{side} {size} @ {entry_price:.2f}"
            )
        else:
            self._position = None
            self._capital.prev_position_size = 0.0
            self._capital.prev_avg_price = 0.0
