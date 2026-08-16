"""Typed, account-preparable execution results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class ZeroDealtReason(StrEnum):
    """Market facts that result in an accepted order with no execution."""

    ABSENT = "absent"
    NONTRADABLE = "nontradable"
    NO_TRADE = "no_trade"


def _decimal(value: Decimal, *, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class Fill:
    """The result for exactly one requested instrument."""

    instrument_id: str
    requested_quantity: Decimal
    dealt_quantity: Decimal
    price: Decimal | None
    reason: ZeroDealtReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        _decimal(self.requested_quantity, name="requested_quantity")
        _decimal(self.dealt_quantity, name="dealt_quantity")
        if self.price is not None:
            _decimal(self.price, name="price")
            if self.price <= 0:
                raise ValueError("price must be positive")
        if self.dealt_quantity == 0:
            if not isinstance(self.reason, ZeroDealtReason):
                raise ValueError("a zero-dealt fill must have a ZeroDealtReason")
            if self.price is not None:
                raise ValueError("a zero-dealt fill must not have a price")
            return
        if self.reason is not None:
            raise ValueError("a dealt fill must not have a zero-dealt reason")
        if self.price is None:
            raise ValueError("a dealt fill must have a price")
        if self.requested_quantity == 0:
            raise ValueError("a dealt fill requires a non-zero requested quantity")
        if self.requested_quantity * self.dealt_quantity < 0:
            raise ValueError("dealt_quantity must have the requested quantity's sign")
        if abs(self.dealt_quantity) > abs(self.requested_quantity):
            raise ValueError("dealt_quantity cannot exceed requested_quantity")


@dataclass(frozen=True, slots=True)
class FillBatch:
    """One complete exchange result, tied to the account state it observed."""

    fills: tuple[Fill, ...]
    account_version_seen: int

    def __post_init__(self) -> None:
        if not isinstance(self.fills, tuple) or any(
            not isinstance(fill, Fill) for fill in self.fills
        ):
            raise TypeError("fills must be a tuple of Fill")
        if isinstance(self.account_version_seen, bool) or not isinstance(
            self.account_version_seen, int
        ):
            raise TypeError("account_version_seen must be an integer")
        if self.account_version_seen < 0:
            raise ValueError("account_version_seen must be non-negative")
        instruments = tuple(fill.instrument_id for fill in self.fills)
        if len(instruments) != len(set(instruments)):
            raise ValueError("a FillBatch may contain each instrument only once")
