"""Typed valuation results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def _decimal(value: Decimal, *, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class Mark:
    """The explicitly selected value of one residual holding."""

    instrument_id: str
    quantity: Decimal
    price: Decimal
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        _decimal(self.quantity, name="quantity")
        _decimal(self.price, name="price")
        _decimal(self.value, name="value")
        if self.quantity == 0:
            raise ValueError("a Mark must represent a residual holding")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.value != self.quantity * self.price:
            raise ValueError("value must equal quantity * price")


@dataclass(frozen=True, slots=True)
class MarkBatch:
    """A complete, non-estimated valuation of all residual holdings."""

    marks: tuple[Mark, ...]
    total_value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.marks, tuple) or any(
            not isinstance(mark, Mark) for mark in self.marks
        ):
            raise TypeError("marks must be a tuple of Mark")
        _decimal(self.total_value, name="total_value")
        instruments = tuple(mark.instrument_id for mark in self.marks)
        if len(instruments) != len(set(instruments)):
            raise ValueError("a MarkBatch may contain each instrument only once")
        if self.total_value != sum((mark.value for mark in self.marks), Decimal("0")):
            raise ValueError("total_value must equal the sum of marks")
