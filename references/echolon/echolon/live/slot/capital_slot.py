"""
Capital Slot
============

Independent capital tracking for a single trading slot.

Each slot has its own capital pool that is completely independent of other
slots and the shared QMT account. This enables parallel multi-strategy
trading with isolated P&L tracking and per-slot drawdown monitoring.

Design rules:
- unrealized_pnl and margin_used are NEVER set by record_trade()
- They are always recomputed by SlotAwarePortfolio.update_mark_to_market()
- record_trade() only updates realized_pnl and peak_equity
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class CapitalSlot:
    """
    Independent capital tracking for one trading slot.

    Tracks: initial capital, realized P&L, peak equity, and bar-level
    mark-to-market fields (unrealized_pnl, margin_used) that are
    recomputed each bar by SlotAwarePortfolio.
    """
    slot_id: str
    initial_capital: float
    realized_pnl: float = 0.0
    peak_equity: float = 0.0

    # Position tracking for state persistence
    prev_position_size: float = 0.0
    prev_avg_price: float = 0.0

    # Bar-level fields — recomputed by update_mark_to_market(), never by record_trade()
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0

    def __post_init__(self):
        if self.peak_equity == 0.0:
            self.peak_equity = self.initial_capital

    @property
    def equity(self) -> float:
        """Current equity = initial_capital + realized_pnl + unrealized_pnl."""
        return self.initial_capital + self.realized_pnl + self.unrealized_pnl

    @property
    def available_cash(self) -> float:
        """Cash available for new positions = equity - margin_used."""
        return self.equity - self.margin_used

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown as positive percentage from peak equity.

        0.0 means at peak, 5.0 means 5% below peak.
        """
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity * 100.0

    def record_trade(self, realized_pnl: float) -> None:
        """
        Record a completed trade's realized P&L.

        Updates realized_pnl and peak_equity only.
        Does NOT touch unrealized_pnl or margin_used.
        """
        self.realized_pnl += realized_pnl
        # Update peak after adding realized
        current_eq = self.equity
        if current_eq > self.peak_equity:
            self.peak_equity = current_eq
        logger.info(
            f"[{self.slot_id}] Trade recorded: realized_pnl={realized_pnl:.2f}, "
            f"cumulative={self.realized_pnl:.2f}, equity={current_eq:.2f}"
        )

    def save_dict(self) -> Dict[str, Any]:
        """Serialize for strategy_state.json custom.capital section."""
        return {
            'slot_id': self.slot_id,
            'initial_capital': self.initial_capital,
            'realized_pnl': self.realized_pnl,
            'peak_equity': self.peak_equity,
            'prev_position_size': self.prev_position_size,
            'prev_avg_price': self.prev_avg_price,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CapitalSlot':
        """Deserialize from strategy_state.json custom.capital section."""
        return cls(
            slot_id=data['slot_id'],
            initial_capital=data['initial_capital'],
            realized_pnl=data.get('realized_pnl', 0.0),
            peak_equity=data.get('peak_equity', data['initial_capital']),
            prev_position_size=data.get('prev_position_size', 0.0),
            prev_avg_price=data.get('prev_avg_price', 0.0),
        )
