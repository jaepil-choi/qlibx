"""Agent-first academic venue declaration.

``vqapr.venues`` is the sole public home for the closed, explicit academic execution venue a
``Simulation`` references as ``exchange``. There is no ``academic=True`` shortcut: instruments,
access, quantity/price grid, and costs are always supplied by the caller, one venue-level grid
applying uniformly to every listed instrument.

Every public declaration is a frozen, slotted, keyword-only value. Constructors reject empty or
duplicate instrument ids, non-finite/non-positive grid steps, and non-finite/negative cost rates.
This module declares algebra only: no execution/fill/order engine lives here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

__all__ = (
    "Academic",
    "Listing",
    "ListingAccess",
    "VenueCost",
)


# --------------------------------------------------------------------------------------
# Shared validation helpers (implementation detail; not part of the public algebra).
# --------------------------------------------------------------------------------------


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


def _unique_identifiers(values: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of strings")
    normalized = tuple(_identifier(value, name=f"{name} entry") for value in values)
    if not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} entries must be unique")
    return normalized


def _finite_positive_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _finite_nonnegative_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


# --------------------------------------------------------------------------------------
# Access and cost declarations.
# --------------------------------------------------------------------------------------


class ListingAccess(StrEnum):
    """How far a venue lets a position on one instrument move.

    ``NONE`` is listed and quoted but never fillable — a benchmark the venue publishes.
    ``LONG_ONLY`` may buy and sell down to zero, but never below it. ``SIGNED`` may hold a
    negative position; the venue claims to model the short.
    """

    NONE = "none"
    LONG_ONLY = "long_only"
    SIGNED = "signed"


@dataclass(frozen=True, slots=True, kw_only=True)
class VenueCost:
    """What one side of a trade costs on this venue, as rates on traded notional.

    Commission and tax stay separate because they are separate economic facts: a venue may
    exempt a category from tax while charging the same commission, and reporting must be able to
    say which of the two a book actually paid.
    """

    side: str
    commission_rate: Decimal
    tax_rate: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "side", _identifier(self.side, name="side"))
        object.__setattr__(
            self,
            "commission_rate",
            _finite_nonnegative_decimal(self.commission_rate, name="commission_rate"),
        )
        object.__setattr__(
            self, "tax_rate", _finite_nonnegative_decimal(self.tax_rate, name="tax_rate")
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Listing:
    """One instrument's explicit access on this venue.

    A venue that lists an instrument always declares both what it *is* (via
    ``instrument_id``) and how far a position on it may move (via ``access``). There is no
    default access — a venue that does not intend to trade an instrument simply omits its
    listing.
    """

    instrument_id: str
    access: ListingAccess

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument_id", _identifier(self.instrument_id, name="instrument_id")
        )
        if not isinstance(self.access, ListingAccess):
            raise TypeError("access must be a ListingAccess")


# --------------------------------------------------------------------------------------
# Academic venue declaration.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Academic:
    """A closed, fully explicit academic execution venue.

    ``listings`` is the complete, non-empty set of instruments this venue trades and their
    access; an instrument absent from ``listings`` is not tradable on this venue. One venue-wide
    ``quantity_step``/``price_step`` grid applies to every listing — this is deliberately not a
    per-instrument grid, matching the academic execution profile's single declared rounding
    convention. ``costs`` is the complete, explicit fee schedule; an empty ``costs`` tuple is a
    free venue, stated rather than defaulted.
    """

    listings: tuple[Listing, ...]
    quantity_step: Decimal
    price_step: Decimal
    costs: tuple[VenueCost, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.listings, tuple) or any(
            not isinstance(listing, Listing) for listing in self.listings
        ):
            raise TypeError("listings must be a tuple of Listing")
        if not self.listings:
            raise ValueError("listings must contain at least one entry")
        instrument_ids = tuple(listing.instrument_id for listing in self.listings)
        if len(set(instrument_ids)) != len(instrument_ids):
            raise ValueError("listings must not repeat an instrument_id")
        object.__setattr__(
            self,
            "quantity_step",
            _finite_positive_decimal(self.quantity_step, name="quantity_step"),
        )
        object.__setattr__(
            self, "price_step", _finite_positive_decimal(self.price_step, name="price_step")
        )
        if not isinstance(self.costs, tuple) or any(
            not isinstance(cost, VenueCost) for cost in self.costs
        ):
            raise TypeError("costs must be a tuple of VenueCost")
        sides = tuple(cost.side for cost in self.costs)
        if len(set(sides)) != len(sides):
            raise ValueError("costs must not declare the same side more than once")

    def listing(self, instrument_id: str) -> Listing:
        """Return the declared Listing for `instrument_id`, or raise if it is not listed."""
        checked = _identifier(instrument_id, name="instrument_id")
        for listing in self.listings:
            if listing.instrument_id == checked:
                return listing
        raise ValueError(f"no listing for {checked!r} on this Academic venue")

    def cost(self, side: str) -> VenueCost | None:
        """Return the declared VenueCost for `side`, or `None` when this venue charges nothing."""
        checked = _identifier(side, name="side")
        for cost in self.costs:
            if cost.side == checked:
                return cost
        return None
