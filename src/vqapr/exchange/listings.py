"""Venue-owned instrument rules and the read-only view order planning consumes.

``ListingRule`` is the venue's authority over one instrument: its quantity unit, its minimum size,
whether it is divisible, and which sides it permits. ``ExchangeRulesView`` is the closed projection
of those rules plus the venue cost declaration, handed to ``plan_orders`` so the intended to
requested conversion can round and clip with the venue's own numbers instead of guessing them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from vqapr.domain.enums import Side
from vqapr.exchange.costs import CostRule, FillCost, charge_fill, effective_rules


@dataclass(frozen=True, slots=True)
class ListingRule:
    """A venue-owned rule for one listed instrument."""

    instrument_id: str
    quantity_step: Decimal
    minimum_quantity: Decimal
    fractional_allowed: bool
    permitted_sides: frozenset[Side]

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        for name, value in (
            ("quantity_step", self.quantity_step),
            ("minimum_quantity", self.minimum_quantity),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.fractional_allowed, bool):
            raise TypeError("fractional_allowed must be a bool")
        if not isinstance(self.permitted_sides, frozenset) or not self.permitted_sides:
            raise ValueError("permitted_sides must be a non-empty frozenset")
        if any(not isinstance(side, Side) for side in self.permitted_sides):
            raise TypeError("permitted_sides must contain Side values")

    def quantize(self, quantity: Decimal) -> Decimal:
        """Round one signed quantity toward zero onto this listing's tradable unit.

        A divisible listing is already on its own unit and is returned unchanged. A lot listing
        floors the magnitude onto ``quantity_step`` and returns exactly zero when the remaining
        magnitude cannot reach ``minimum_quantity``.
        """
        if not isinstance(quantity, Decimal):
            raise TypeError("quantity must be a Decimal")
        if not quantity.is_finite():
            raise ValueError("quantity must be finite")
        if self.fractional_allowed or quantity == 0:
            return quantity
        magnitude = abs(quantity)
        steps = (magnitude / self.quantity_step).to_integral_value(rounding="ROUND_FLOOR")
        quantized = steps * self.quantity_step
        if quantized < self.minimum_quantity:
            return Decimal("0")
        return quantized if quantity > 0 else -quantized

    def permits(self, side: Side) -> bool:
        return side in self.permitted_sides


@dataclass(frozen=True, slots=True)
class ExchangeRulesView:
    """The closed, read-only venue projection that order planning is allowed to consume."""

    exchange_id: str
    listings: Mapping[str, ListingRule]
    costs: tuple[CostRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.exchange_id, str) or not self.exchange_id:
            raise ValueError("exchange_id must be a non-empty string")
        if not isinstance(self.listings, Mapping):
            raise TypeError("listings must be a mapping")
        for instrument_id, rule in self.listings.items():
            if not isinstance(rule, ListingRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its ListingRule instrument_id")
        if not isinstance(self.costs, tuple) or any(
            not isinstance(rule, CostRule) for rule in self.costs
        ):
            raise TypeError("costs must be a tuple of CostRule")
        object.__setattr__(self, "listings", dict(self.listings))

    def listing(self, instrument_id: str) -> ListingRule:
        try:
            return self.listings[instrument_id]
        except KeyError as error:
            raise ValueError(f"no listing for {instrument_id!r} on {self.exchange_id!r}") from error

    def quantize(self, instrument_id: str, quantity: Decimal) -> Decimal:
        return self.listing(instrument_id).quantize(quantity)

    def at(self, instant: datetime) -> ExchangeRulesView:
        """Bind this declaration to one execution instant.

        Flat rates are already instant-independent and return an equivalent view. A venue that
        declares effective-dated bands is narrowed here, so everything downstream keeps charging
        against a single unambiguous rule per side.
        """
        if not self.costs or all(rule.always_effective for rule in self.costs):
            return self
        return replace(self, costs=effective_rules(self.costs, instant))

    def charge(self, side: Side, notional: Decimal, at: datetime | None = None) -> FillCost:
        """Charge the single effective rule for ``side``; an undeclared venue charges nothing."""
        if not self.costs:
            return FillCost()
        return charge_fill(self.costs, side, notional, at)

    @property
    def declaration_identity(self) -> tuple[object, ...]:
        return (
            self.exchange_id,
            tuple(
                (
                    rule.instrument_id,
                    str(rule.quantity_step),
                    str(rule.minimum_quantity),
                    rule.fractional_allowed,
                    tuple(sorted(side.value for side in rule.permitted_sides)),
                )
                for rule in sorted(self.listings.values(), key=lambda item: item.instrument_id)
            ),
            tuple(rule.declaration_identity for rule in self.costs),
        )


def rules_view(
    exchange_id: str,
    listings: Mapping[str, ListingRule],
    costs: Sequence[CostRule] = (),
) -> ExchangeRulesView:
    return ExchangeRulesView(exchange_id, listings, tuple(costs))
