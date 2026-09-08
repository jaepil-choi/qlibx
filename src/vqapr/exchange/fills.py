"""Typed, account-preparable execution results."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from vqapr.domain.instruments import InstrumentKind
from vqapr.exchange.costs import FillCost


class ZeroDealtReason(StrEnum):
    """Facts that result in an accepted order with no execution.

    The first three are facts about the MARKET: the venue published no row, published one saying
    the name could not trade, or the plan asked for no change. `UNFUNDED` is a fact about the
    ACCOUNT, and it is named separately for that reason -- a reader summing zero-dealt orders to
    ask "what did the market refuse me" must not have their own empty purse counted in the answer.
    """

    ABSENT = "absent"
    NONTRADABLE = "nontradable"
    NO_TRADE = "no_trade"
    UNFUNDED = "unfunded"
    """The batch ran out of cash before reaching this buy.

    Only a venue profile that charges and rounds to whole units can produce this. A fractional
    profile sizes exactly to the cash it has, so there is no residual for the money to run out
    against.
    """


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
    cost: FillCost = field(default_factory=FillCost)
    kind: InstrumentKind | None = None
    """The category this fill was charged as, or ``None`` when the venue declared none.

    Carried on the fill rather than looked up afterwards because a fill is *evidence*: it records
    what the venue actually charged it as, and a roster edited later must not change what a past
    fill says it paid. It is also what lets a consumer that has no ``ExchangeRulesView`` -- a run
    record, a report -- separate an ETF sleeve's cost from the direct book's.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if self.kind is not None and not isinstance(self.kind, InstrumentKind):
            raise TypeError("kind must be an InstrumentKind or None")
        _decimal(self.requested_quantity, name="requested_quantity")
        _decimal(self.dealt_quantity, name="dealt_quantity")
        if not isinstance(self.cost, FillCost):
            raise TypeError("cost must be a FillCost")
        if self.price is not None:
            _decimal(self.price, name="price")
            if self.price <= 0:
                raise ValueError("price must be positive")
        if self.dealt_quantity == 0:
            if not isinstance(self.reason, ZeroDealtReason):
                raise ValueError("a zero-dealt fill must have a ZeroDealtReason")
            if self.price is not None:
                raise ValueError("a zero-dealt fill must not have a price")
            if self.cost.total != 0:
                raise ValueError("a zero-dealt fill must not charge a cost")
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

    @classmethod
    def zero_dealt(
        cls, instrument_id: str, requested_quantity: Decimal, reason: ZeroDealtReason
    ) -> Fill:
        """An accepted order the venue did not execute, for the stated market or account fact.

        Every profile writes this same fill -- no price, no cost, nothing dealt -- for each of the
        `ZeroDealtReason` facts, and did so as five positional arguments repeated in two venues.
        One constructor keeps the shape of "nothing happened" in one place, so a venue adding a
        reason cannot spell the evidence differently from the others.
        """
        return cls(instrument_id, requested_quantity, Decimal("0"), None, reason)

    @property
    def notional(self) -> Decimal:
        """The absolute traded value before cost."""
        if self.price is None:
            return Decimal("0")
        return abs(self.dealt_quantity) * self.price

    @property
    def cash_delta(self) -> Decimal:
        """The exact signed cash movement this fill causes, cost included."""
        if self.price is None:
            return Decimal("0")
        return -(self.dealt_quantity * self.price) - self.cost.total


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
