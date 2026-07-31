#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""
Enhanced Position Class with Contract Information
=================================================

Position class that tracks the contract in which a position was opened,
enabling accurate position reporting and PnL calculations without
requiring explicit symbol parameters.

MIGRATED FROM: modules/backtest/backtesting/engine/enhanced_position.py
Changes:
- No functional changes (market-agnostic component)
"""

import logging
from backtrader.position import Position as BasePosition
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class EnhancedPosition(BasePosition):
    """
    Enhanced Position class that includes contract/symbol information.

    This class extends the standard backtrader Position to track:
    - The contract in which the position was opened
    - When the position was last updated
    - Additional metadata for position tracking
    """

    def __init__(self, size=0, price=0.0, contract=None, **kwargs):
        """
        Initialize enhanced position with contract information.

        Parameters
        ----------
        size : int
            Position size (positive for long, negative for short)
        price : float
            Position price
        contract : str, optional
            Contract/symbol identifier
        **kwargs
            Additional keyword arguments for the base Position class
        """
        super(EnhancedPosition, self).__init__(size, price)

        # Enhanced attributes
        self.contract = contract
        self.symbol = contract  # Alias for compatibility
        self._creation_info = kwargs.get('creation_info', {})

        logger.debug(f"Enhanced position created: size={size}, price={price}, contract={contract}")

    @property
    def direction(self) -> str:
        """Get position direction based on size."""
        if self.size > 0:
            return "LONG"
        elif self.size < 0:
            return "SHORT"
        else:
            return "FLAT"

    def update_contract(self, contract: str) -> None:
        """
        Update the contract information for this position.

        Parameters
        ----------
        contract : str
            New contract identifier
        """
        old_contract = self.contract
        self.contract = contract
        self.symbol = contract  # Keep alias in sync

        if old_contract != contract:
            logger.debug(f"Position contract updated: {old_contract} -> {contract}")

    @property
    def opened(self) -> int:
        """Get the opened quantity (for observer compatibility)."""
        return getattr(self, 'upopened', self.size)

    @property
    def closed(self) -> int:
        """Get the closed quantity (for observer compatibility)."""
        return getattr(self, 'upclosed', 0)

    def clone(self) -> 'EnhancedPosition':
        """
        Override clone to preserve contract information.

        Returns
        -------
        EnhancedPosition
            Cloned position with all attributes preserved
        """
        cloned = EnhancedPosition(
            size=self.size,
            price=self.price,
            contract=self.contract,
            creation_info=self._creation_info.copy()
        )

        # Copy all base class attributes
        cloned.price_orig = getattr(self, 'price_orig', self.price)
        cloned.adjbase = getattr(self, 'adjbase', None)
        cloned.upopened = getattr(self, 'upopened', self.size)
        cloned.upclosed = getattr(self, 'upclosed', 0)
        cloned.updt = getattr(self, 'updt', None)

        return cloned

    def __str__(self) -> str:
        """Enhanced string representation with contract information."""
        items = []
        items.append('--- Enhanced Position Begin')
        items.append(f'- Contract: {self.contract}')
        items.append(f'- Size: {self.size}')
        items.append(f'- Price: {self.price}')
        items.append(f'- Price orig: {getattr(self, "price_orig", self.price)}')
        items.append(f'- Closed: {getattr(self, "upclosed", 0)}')
        items.append(f'- Opened: {getattr(self, "upopened", self.size)}')
        items.append(f'- Adjbase: {getattr(self, "adjbase", None)}')
        items.append('--- Enhanced Position End')
        return '\n'.join(items)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert position to dictionary representation.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing position information
        """
        return {
            'contract': self.contract,
            'symbol': self.symbol,
            'size': self.size,
            'price': self.price,
            'price_orig': getattr(self, 'price_orig', self.price),
            'upopened': getattr(self, 'upopened', self.size),
            'upclosed': getattr(self, 'upclosed', 0),
            'adjbase': getattr(self, 'adjbase', None),
            'creation_info': self._creation_info
        }

    @classmethod
    def from_base_position(cls, base_pos, contract: Optional[str] = None, **kwargs) -> 'EnhancedPosition':
        """
        Create an EnhancedPosition from a standard backtrader Position.

        Parameters
        ----------
        base_pos : backtrader.Position
            Standard backtrader position
        contract : str, optional
            Contract identifier to add
        **kwargs
            Additional creation parameters

        Returns
        -------
        EnhancedPosition
            Enhanced position with copied attributes
        """
        enhanced = cls(
            size=base_pos.size,
            price=base_pos.price,
            contract=contract,
            creation_info=kwargs
        )

        # Copy base class attributes
        enhanced.price_orig = getattr(base_pos, 'price_orig', base_pos.price)
        enhanced.adjbase = getattr(base_pos, 'adjbase', None)
        enhanced.upopened = getattr(base_pos, 'upopened', base_pos.size)
        enhanced.upclosed = getattr(base_pos, 'upclosed', 0)
        enhanced.updt = getattr(base_pos, 'updt', None)

        return enhanced
