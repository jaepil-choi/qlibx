"""Typed, immutable economic budget declarations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


def _finite_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


class PortfolioDirection(StrEnum):
    """The signedness permitted for a complete intended portfolio."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


@dataclass(frozen=True, slots=True)
class Budget:
    """Declared cash and per-position bounds for one economic intent.

    The declaration is a value, not a strategy-owned mutable configuration.  It
    therefore travels with the intent and is independently checked at the Flow
    boundary.
    """

    direction: PortfolioDirection
    cash_lower: Decimal
    cash_upper: Decimal
    target_lower: Decimal
    target_upper: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.direction, PortfolioDirection):
            raise TypeError("direction must be a PortfolioDirection")
        for name in ("cash_lower", "cash_upper", "target_lower", "target_upper"):
            _finite_decimal(getattr(self, name), name=name)
        if self.cash_lower > self.cash_upper:
            raise ValueError("cash_lower must not exceed cash_upper")
        if self.target_lower > self.target_upper:
            raise ValueError("target_lower must not exceed target_upper")
        if self.direction is PortfolioDirection.LONG_ONLY and (
            self.cash_lower < 0 or self.target_lower < 0
        ):
            raise ValueError("long_only budgets cannot permit negative cash or targets")

    def validates_cash(self, value: Decimal) -> bool:
        """Return whether an already-validated cash target is within this budget."""
        return self.cash_lower <= value <= self.cash_upper

    def validates_target(self, value: Decimal) -> bool:
        """Return whether an already-validated target is within this budget."""
        return self.target_lower <= value <= self.target_upper
