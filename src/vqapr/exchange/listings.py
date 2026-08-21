"""What a venue will do with one instrument, and the read-only view order planning consumes.

``TradeRule`` is the venue's whole authority over one instrument: the unit it trades in, how far
its position may move, and what each side costs. ``ExchangeRulesView`` is the closed projection of
those rules handed to ``plan_orders``, so the intended-to-requested conversion rounds and charges
with the venue's own numbers instead of guessing them.

**Quantity and cost are one rule, not two.** They were split because canon separated things by how
fast they change -- units never, rates by period -- but nothing ever declared a period-dependent
rate, and the machinery that supported it was dead. With rates flat, both halves answer the same
question at the same rate of change: *what will this venue do with this instrument?* Minimum size,
lot unit and fractional divisibility are as much "may this trade" facts as a rate is a "what does
it cost" fact, and a venue that lists an instrument always knows both.

Two declarations still meet here, and those are genuinely different (canon 2.8):

    what an instrument *is*      ``Instrument``  -- category, venue-independent
    what this venue does with it ``TradeRule``   -- unit, access, cost

The join is by ``instrument_id``. ``TradeTerms`` declares one rule per *category* and expands it,
because a venue rarely has three thousand distinct rules -- but the resolved form stays
per-instrument, because some venues genuinely do (HKEX board lots differ by instrument).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from vqapr.domain.enums import Side
from vqapr.domain.instruments import Instrument, InstrumentKind, base_notional, base_quantity_for
from vqapr.exchange.costs import FREE, FillCost, SideCost


class ListingAccess(StrEnum):
    """How far a venue lets a position on one instrument move.

    This replaces a set of permitted order *directions*, which conflated two different facts and
    got the common case wrong: a listing that permitted only ``BUY`` refused to sell shares the
    account already owned. Selling what you hold is not short selling, and no venue forbids it
    while still letting you buy.

    Three states, so the impossible combinations cannot be written down:

        NONE       listed and quoted, never filled -- a benchmark the venue publishes
        LONG_ONLY  may buy, and may sell down to zero, but never below it
        SIGNED     may hold a negative position; the venue claims to model the short
    """

    NONE = "none"
    LONG_ONLY = "long_only"
    SIGNED = "signed"


_BASE_RULE_FIELDS = frozenset(
    {
        "instrument_id",
        "quantity_step",
        "minimum_quantity",
        "fractional_allowed",
        "access",
        "buy",
        "sell",
    }
)
"""The fields every venue shares. Anything else on a rule belongs to one venue's own regime."""


@dataclass(frozen=True, slots=True)
class TradeRule:
    """Everything one venue will do with one instrument.

    Venue-specific regimes subclass this. A price limit is a percentage in Korea and China but a
    fixed band table in Japan, and a same-day resale ban exists only in China -- those are
    different *shapes*, not different values, so they are declared as typed fields on a subclass
    rather than squeezed into a shared field or a free-form dictionary. A typed subclass fails at
    venue construction when a field is misspelled or missing; a dictionary fails mid-run, or does
    not fail at all.
    """

    instrument_id: str
    quantity_step: Decimal
    minimum_quantity: Decimal
    fractional_allowed: bool
    access: ListingAccess = ListingAccess.LONG_ONLY
    buy: SideCost = FREE
    sell: SideCost = FREE

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
        if not isinstance(self.access, ListingAccess):
            raise TypeError("access must be a ListingAccess")
        for name, value in (("buy", self.buy), ("sell", self.sell)):
            if not isinstance(value, SideCost):
                raise TypeError(f"{name} must be a SideCost")

    def quantize(self, quantity: Decimal) -> Decimal:
        """Round one signed quantity toward zero onto this rule's tradable unit.

        A divisible instrument is already on its own unit, so only its **floor** applies: a size
        below ``minimum_quantity`` is not a smaller order, it is no order, and returning it
        unchanged produced a request the venue then refused outright --

            quantity violates listing rule for 'A267250'   delta 3.76E-7, minimum 1E-6

        which ends a run. That delta is not a mistake by the caller: a held position sits wherever
        the last fills left it, so ``desired - held`` is an arbitrary real number and lands under
        the floor whenever a target barely moves. Record 039 separated the floor from the grid in
        :meth:`permits_quantity` and this method was left checking neither for a fractional
        listing, so planning and validation disagreed about the same order.

        A lot instrument floors the magnitude onto ``quantity_step`` and likewise returns exactly
        zero when what remains cannot reach ``minimum_quantity``.
        """
        if not isinstance(quantity, Decimal):
            raise TypeError("quantity must be a Decimal")
        if not quantity.is_finite():
            raise ValueError("quantity must be finite")
        if quantity == 0:
            return quantity
        if self.fractional_allowed:
            return quantity if abs(quantity) >= self.minimum_quantity else Decimal("0")
        magnitude = abs(quantity)
        steps = (magnitude / self.quantity_step).to_integral_value(rounding="ROUND_FLOOR")
        quantized = steps * self.quantity_step
        if quantized < self.minimum_quantity:
            return Decimal("0")
        return quantized if quantity > 0 else -quantized

    @property
    def tradable(self) -> bool:
        """Whether this venue will fill this instrument in any direction.

        ``NONE`` is a venue declaring *listed, never fillable* -- a benchmark it publishes and
        quotes but does not trade. This is the only place tradability is expressed; canon 6.2 keeps
        it off ``Instrument`` so the same instrument can be tradable on one venue and not another.

        This is the venue's standing judgement, not today's. A halt is time-varying and lives in
        the execution table, which produces a typed ``NONTRADABLE`` zero-dealt result instead, and
        so does a delisting -- the row simply stops appearing and the fill is typed ``ABSENT``.
        """
        return self.access is not ListingAccess.NONE

    @property
    def short_allowed(self) -> bool:
        return self.access is ListingAccess.SIGNED

    def permits_position(self, held: Decimal, delta: Decimal) -> bool:
        """Whether this venue lets a position move from ``held`` by ``delta``.

        The question a venue actually answers. Closing or reducing is always permitted on a
        tradable instrument -- selling what you own is not short selling -- and only the
        *resulting* position being negative requires the venue to have claimed it models the short.
        """
        if not self.tradable:
            return delta == 0
        return self.short_allowed or held + delta >= 0

    def permits_quantity(self, quantity: Decimal) -> bool:
        """Whether an absolute order size is one this venue can actually fill.

        Two independent facts, checked independently:

            minimum_quantity  the smallest size the venue will accept at all
            quantity_step     the unit sizes must land on, when the instrument is not divisible

        They were previously collapsed into ``quantity != quantize(quantity)``, which is wrong for
        a divisible instrument: ``quantize`` returns a fractional quantity unchanged, so the
        round-trip always matched and **the minimum was never checked**. A fractional venue would
        accept an order below its own declared floor. The academic profile spelled the same check
        as three separate conditions and did not have the bug, which is exactly the drift that
        duplicated validation produces.
        """
        if not isinstance(quantity, Decimal):
            raise TypeError("quantity must be a Decimal")
        if not quantity.is_finite() or quantity < 0:
            return False
        if quantity < self.minimum_quantity:
            return False
        if self.fractional_allowed:
            # A divisible instrument declares its own divisibility, so any size at or above the
            # minimum is on its unit by definition.
            return True
        steps = quantity / self.quantity_step
        return steps == steps.to_integral_value()

    def cost(self, side: Side) -> SideCost:
        return self.buy if side is Side.BUY else self.sell

    def charge(self, side: Side, notional: Decimal) -> FillCost:
        """Charge this instrument's own rate for ``side``."""
        if not isinstance(side, Side):
            raise TypeError("side must be a Side")
        return self.cost(side).charge(notional)

    @property
    def declaration_identity(self) -> tuple[object, ...]:
        """The immutable declaration this rule contributes to a venue's fingerprint.

        A venue subclass that adds a field -- a price-limit rate, a lot-unit convention -- must
        appear here or the workspace treats two different declarations as the same one, and a rate
        change silently reuses a frozen component. Subclass fields are therefore collected
        automatically from the dataclass definition rather than by hand, so adding a field cannot
        forget to extend the identity.
        """
        return (
            type(self).__name__,
            self.instrument_id,
            str(self.quantity_step),
            str(self.minimum_quantity),
            self.fractional_allowed,
            self.access.value,
            self.buy.declaration_identity,
            self.sell.declaration_identity,
            self._extra_identity(),
        )

    def _extra_identity(self) -> tuple[tuple[str, str], ...]:
        """Every field a subclass declared beyond the base ones, in declared order."""
        return tuple(
            (name, str(getattr(self, name)))
            for name in self.__dataclass_fields__
            if name not in _BASE_RULE_FIELDS
        )


@dataclass(frozen=True, slots=True)
class ExecutionFieldRequirement:
    """One declared execution-table price a venue needs in order to apply a regime.

    A venue asks for a **number the user already has**, never for a conclusion. KRX needs the
    session's base price to compute its limit band; it does not ask the user whether a name is
    limit-up, because that is the exchange's rule and putting it in the registration would make
    every user reimplement a market's regulations.

    ``feature`` names the regime that needs it, so a preflight refusal can say what to switch off
    rather than only what is missing.
    """

    price: str
    feature: str

    def __post_init__(self) -> None:
        for name, value in (("price", self.price), ("feature", self.feature)):
            if not isinstance(value, str) or not value or value.strip() != value:
                raise ValueError(f"{name} must be a non-empty unpadded string")


@dataclass(frozen=True, slots=True)
class TradeTerms:
    """One venue's terms for a whole instrument category, before they name an instrument.

    KRX trades every share and every ETF in whole units and charges each category one pair of
    rates, so declaring that twice and expanding it is the honest declaration; writing three
    thousand identical rules states the same fact three thousand times and invites drift.
    """

    quantity_step: Decimal
    minimum_quantity: Decimal
    fractional_allowed: bool
    access: ListingAccess = ListingAccess.LONG_ONLY
    buy: SideCost = FREE
    sell: SideCost = FREE

    def for_instrument(self, instrument_id: str) -> TradeRule:
        return TradeRule(
            instrument_id,
            self.quantity_step,
            self.minimum_quantity,
            self.fractional_allowed,
            self.access,
            self.buy,
            self.sell,
        )


def trade_rules_by_kind(
    instruments: Mapping[str, Instrument],
    terms: Mapping[InstrumentKind, TradeTerms],
) -> dict[str, TradeRule]:
    """Expand one set of terms per category into the per-instrument rules a venue holds.

    An instrument whose category has no terms is *not listed*, which is how a venue declines a
    whole category -- KRX lists no factors -- without naming every instrument in it.
    """
    if not isinstance(instruments, Mapping) or not isinstance(terms, Mapping):
        raise TypeError("instruments and terms must be mappings")
    for kind, rule in terms.items():
        if not isinstance(kind, InstrumentKind) or not isinstance(rule, TradeTerms):
            raise TypeError("terms must map InstrumentKind to TradeTerms")
    return {
        instrument_id: terms[declared.kind].for_instrument(instrument_id)
        for instrument_id, declared in instruments.items()
        if declared.kind in terms
    }


@dataclass(frozen=True, slots=True)
class ExchangeRulesView:
    """The closed, read-only venue projection that order planning is allowed to consume."""

    exchange_id: str
    listings: Mapping[str, TradeRule]
    instruments: Mapping[str, Instrument] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.exchange_id, str) or not self.exchange_id:
            raise ValueError("exchange_id must be a non-empty string")
        if not isinstance(self.listings, Mapping):
            raise TypeError("listings must be a mapping")
        for instrument_id, rule in self.listings.items():
            if not isinstance(rule, TradeRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its TradeRule instrument_id")
        if not isinstance(self.instruments, Mapping):
            raise TypeError("instruments must be a mapping")
        for instrument_id, declared in self.instruments.items():
            if not isinstance(declared, Instrument) or instrument_id != declared.instrument_id:
                raise ValueError("each instrument key must match its Instrument instrument_id")
            if instrument_id not in self.listings:
                raise ValueError(
                    f"instrument {instrument_id!r} is declared on {self.exchange_id!r} "
                    "without a listing"
                )
        object.__setattr__(self, "listings", dict(self.listings))
        object.__setattr__(self, "instruments", dict(self.instruments))

    def listing(self, instrument_id: str) -> TradeRule:
        try:
            return self.listings[instrument_id]
        except KeyError as error:
            raise ValueError(f"no listing for {instrument_id!r} on {self.exchange_id!r}") from error

    def instrument(self, instrument_id: str) -> Instrument | None:
        """The declared instrument, or ``None`` when this venue declares no category for it."""
        return self.instruments.get(instrument_id)

    def kind(self, instrument_id: str) -> InstrumentKind | None:
        declared = self.instruments.get(instrument_id)
        return None if declared is None else declared.kind

    def tradable(self, instrument_id: str) -> bool:
        """Whether this venue will fill this instrument in any direction."""
        rule = self.listings.get(instrument_id)
        return rule is not None and rule.tradable

    def quantize(self, instrument_id: str, quantity: Decimal) -> Decimal:
        return self.listing(instrument_id).quantize(quantity)

    def notional(self, instrument_id: str, quantity: Decimal, price: Decimal) -> Decimal:
        """The absolute traded value, asking the instrument when the venue declares one.

        Routed through the instrument so a category whose contract is not one unit of the quoted
        price -- a future with a multiplier -- changes this number by overriding one method,
        without order planning or any venue learning what a multiplier is.
        """
        declared = self.instruments.get(instrument_id)
        if declared is None:
            return base_notional(quantity, price)
        return declared.notional(quantity, price)

    def quantity_for(self, instrument_id: str, value: Decimal, price: Decimal) -> Decimal:
        """The signed quantity reaching ``value`` of exposure, the inverse of :meth:`notional`."""
        declared = self.instruments.get(instrument_id)
        if declared is None:
            return base_quantity_for(value, price)
        return declared.quantity_for(value, price)

    def charge(self, side: Side, notional: Decimal, instrument_id: str) -> FillCost:
        """Charge the instrument's own rate for ``side``.

        A dictionary lookup, not a match: an instrument the venue lists has exactly one rule, so
        charging zero bands or several is not a failure mode that exists.
        """
        return self.listing(instrument_id).charge(side, notional)

    @property
    def declaration_identity(self) -> tuple[object, ...]:
        return (
            self.exchange_id,
            tuple(
                rule.declaration_identity
                for rule in sorted(self.listings.values(), key=lambda item: item.instrument_id)
            ),
            tuple(
                declared.declaration_identity
                for declared in sorted(
                    self.instruments.values(), key=lambda item: item.instrument_id
                )
            ),
        )


def rules_view(
    exchange_id: str,
    listings: Mapping[str, TradeRule],
    instruments: Mapping[str, Instrument] | None = None,
) -> ExchangeRulesView:
    return ExchangeRulesView(exchange_id, listings, dict(instruments or {}))
