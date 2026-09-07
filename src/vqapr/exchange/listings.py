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
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from vqapr.domain.instruments import (
    INSTRUMENT_TYPES,
    Instrument,
    InstrumentKind,
    base_notional,
    base_quantity_for,
)
from vqapr.domain.values import Side
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
    registry: object | None = None
    terms_by_kind: Mapping[object, object] | None = None
    """Per-category terms, for a venue whose rate depends on what an instrument IS.

    Present, the charge is resolved from the ROSTER at fill time rather than from the rule the
    venue was constructed with. That is the difference between a venue that reads a category and
    one that declares it: the first borrows the project's answer, the second keeps its own and can
    disagree with it.

    Absent, the listing's own `buy`/`sell` are charged, which is right for a venue whose rate does
    not vary by category -- the academic profile charges nothing, and a flat-rate venue charges the
    same thing to everything.

    Keeping the terms here rather than on each `TradeRule` is what removes the duplication. A rule
    still says how an instrument TRADES -- its step, its minimum, its price band -- and those are
    the venue's own facts. What it COSTS depends on a category the project owns, so it is resolved
    where the project's answer is available and nowhere else.
    """
    """The project's instrument roster, handed in at run assembly. ACCESS, never ownership.

    A venue reading what an instrument is, is right; a venue DECLARING it is the defect issue 008
    removes. `kind` answers no to both axes canon 2.8 splits an instrument's facts along -- a
    stock does not become an ETF, and it is a stock on every venue -- so the fact belongs to the
    project and the venue borrows it.

    The distinction is not cosmetic. The venues themselves no longer take an `instruments`
    parameter at all, so a venue author has no channel through which to declare a category, and
    the only way one arrives is `with_registry` at run assembly. A constructor field on the venue
    would quietly recreate exactly what was removed.

    `None` is legal to CONSTRUCT and refuses to RESOLVE. `loading.py` type-checks `rules` before
    the registry is injected, so a registry-less view must be constructible; and every method that
    needs a category raises rather than falling back, because a fallback here is the silent
    default this whole design exists to eliminate.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.exchange_id, str) or not self.exchange_id:
            raise ValueError("exchange_id must be a non-empty string")
        if not isinstance(self.listings, Mapping):
            raise TypeError("listings must be a mapping")
        for instrument_id, rule in self.listings.items():
            if not isinstance(rule, TradeRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its TradeRule instrument_id")
        object.__setattr__(self, "listings", dict(self.listings))
        object.__setattr__(self, "registry", self._as_registry(self.registry))

    @staticmethod
    def _as_registry(registry: object) -> object:
        """Accept a roster, or a plain `{instrument_id: Instrument}` meaning the same thing.

        A mapping is the honest minimum this view needs -- it only ever asks "what is this id" --
        and refusing one would force every caller that already holds instruments to wrap it for no
        gain. The roster type is what registration produces; a mapping is what a test or an
        in-process assembly naturally has.
        """
        if registry is None or hasattr(registry, "instrument"):
            return registry
        if isinstance(registry, Mapping):
            from vqapr.domain.instruments import InstrumentRoster

            return InstrumentRoster(registry)
        raise TypeError("registry must expose instrument(id), or be a mapping of them")

    def with_registry(self, registry: object) -> ExchangeRulesView:
        """This view, bound to the project's roster. The one seam a category enters through.

        Returns a new view rather than mutating: a venue instance may be shared, and a run binding
        its registry into somebody else's venue would be a side effect nobody declared.
        """
        return ExchangeRulesView(
            self.exchange_id,
            self.listings,
            self._as_registry(registry),
            self.terms_by_kind,
        )

    def _declared(self, instrument_id: str) -> Instrument:
        """The instrument's declared identity, refusing rather than guessing.

        Both refusals name what to do, because a run stopped here is a run whose author has not
        yet said what they are trading -- and that is a repair, not a defect.
        """
        if self.registry is None:
            raise ValueError(
                f"no instrument roster reached {self.exchange_id!r}, so {instrument_id!r} "
                "cannot be identified; register instruments and run through the Flow"
            )
        return self.registry.instrument(instrument_id)

    def listing(self, instrument_id: str) -> TradeRule:
        try:
            return self.listings[instrument_id]
        except KeyError as error:
            raise ValueError(f"no listing for {instrument_id!r} on {self.exchange_id!r}") from error

    def instrument(self, instrument_id: str) -> Instrument:
        """The declared instrument, refusing an id the project never described."""
        return self._declared(instrument_id)

    def kind(self, instrument_id: str) -> InstrumentKind:
        """The instrument's category, refusing an id the project never described.

        Raising rather than returning `None` is what closes issue 007. It returned `None` for an
        undescribed id, and every caller then decided for itself what that meant -- which is how
        an ETF came to pay the sale tax KRX exempts it from.

        Use `stamped_kind` where an answer is merely being RECORDED rather than acted on.
        """
        return self._declared(instrument_id).kind

    def stamped_kind(self, instrument_id: str) -> InstrumentKind | None:
        """The category to record on a fill, or `None` when the project described none.

        Separate from `kind` because stamping and charging ask different questions. Charging asks
        "what rate applies", which has no honest answer for an undescribed id, so it refuses.
        Stamping asks "what should this fill say it was", and `None` IS the honest answer there:
        the run genuinely did not know, and recording that is more truthful than refusing to
        record anything.

        Keeping them apart is what lets a run with no roster still execute on a venue that charges
        one flat rate, while a venue whose rate depends on the category still refuses. The
        difference is visible in the record afterwards: a fill stamped `None` says the category
        was never declared.
        """
        if self.registry is None or not self.registry.declares(instrument_id):
            return None
        return self.registry.instrument(instrument_id).kind

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

        **Falls back to the base conversion only when no roster reached this view, and only
        because no shipped category overrides it.** All four -- stock, etf, index, factor -- use
        `base_notional` unchanged, so for every category that exists today the fallback and the
        declared answer are the same number. Refusing here would stop a run to compute a value it
        would have computed identically.

        That is a statement about today, and it has an expiry. The first category that overrides
        this pair -- a future with a contract multiplier is the obvious one -- makes the fallback
        wrong by exactly that multiplier, silently, on the order-sizing path. `_sizing_is_uniform`
        below is what makes that moment loud instead: it fails the moment an override appears, so
        this branch cannot outlive the assumption it rests on.

        Charging is different and refuses immediately, because a category's RATE differs today:
        KRX exempts an ETF from the sale tax a share pays. That is the defect issue 007 found, and
        it is closed by `kind` raising rather than returning `None`.
        """
        if self.registry is None and _sizing_is_uniform():
            return base_notional(quantity, price)
        return self._declared(instrument_id).notional(quantity, price)

    def quantity_for(self, instrument_id: str, value: Decimal, price: Decimal) -> Decimal:
        """The signed quantity reaching ``value`` of exposure, the inverse of :meth:`notional`."""
        if self.registry is None and _sizing_is_uniform():
            return base_quantity_for(value, price)
        return self._declared(instrument_id).quantity_for(value, price)

    def charge(self, side: Side, notional: Decimal, instrument_id: str) -> FillCost:
        """Charge the rate that applies to this instrument on this side.

        When the venue declares per-category terms, the category comes from the ROSTER, through
        `_declared` -- the same source `stamped_kind` reads. Before this, `charge` read the rule
        the venue was constructed with while `stamped_kind` read the registry, so a fill could say
        one category and be charged as another, silently, on a run that completed `ok:true`
        (issue 013).

        `_declared` refuses rather than defaulting when no roster reached the venue. That is the
        correct failure for a venue whose rate depends on the category: there is no honest answer
        for an undescribed id, and charging one rate anyway is the silent default this design
        exists to remove. A venue with flat terms still runs without a roster, because it takes the
        branch below.
        """
        if self.terms_by_kind is not None:
            # `listing` first, so an id this venue does not trade is refused as that rather than as
            # a category problem.
            self.listing(instrument_id)
            terms = self.terms_by_kind.get(self._declared(instrument_id).kind)
            if terms is None:
                raise ValueError(
                    f"{self.exchange_id!r} declares no terms for "
                    f"{self._declared(instrument_id).kind}, which is what the registered roster "
                    f"says {instrument_id!r} is; list it under a category this venue trades, or "
                    f"correct the roster"
                )
            return terms.for_instrument(instrument_id).charge(side, notional)
        return self.listing(instrument_id).charge(side, notional)

    @property
    def declaration_identity(self) -> tuple[object, ...]:
        """What this venue declares, which no longer includes the roster.

        The roster was folded in here, so adding one never-traded instrument to a universe changed
        a venue's fingerprint while its behaviour did not move -- a re-registration conflict
        manufactured out of nothing. A roster belongs in no fingerprint: what a past run treated
        an instrument as is testified to by that run's own fills.
        """
        return (
            self.exchange_id,
            tuple(
                rule.declaration_identity
                for rule in sorted(self.listings.values(), key=lambda item: item.instrument_id)
            ),
        )


def _sizing_is_uniform() -> bool:
    """Whether every shipped category still sizes the same way the base conversion does.

    True today: `notional`/`quantity_for` are declared on `Instrument` and no subclass overrides
    them, so a stock, an ETF, an index and a factor all convert money to quantity identically.
    While that holds, sizing an instrument the roster never described produces the same number the
    roster would have produced, and refusing would buy nothing.

    It stops holding the moment a category with its own contract size is added -- a future, an
    option -- and this returns False at exactly that moment, which turns the fallback above off
    without anybody having to remember it exists. That is the point: the assumption is checked by
    the code that depends on it, not by a comment asking a future reader to be careful.

    Computed per call rather than cached, because `INSTRUMENT_TYPES` is the registry a new
    category is added to and a cached answer would be stale exactly when it mattered.
    """
    return not any(
        "notional" in category.__dict__ or "quantity_for" in category.__dict__
        for category in INSTRUMENT_TYPES.values()
    )


def rules_view(
    exchange_id: str,
    listings: Mapping[str, TradeRule],
    registry: object | None = None,
    terms_by_kind: Mapping[object, TradeTerms] | None = None,
) -> ExchangeRulesView:
    """A view over one venue's listings, optionally already bound to a roster.

    The roster stays optional here because construction must succeed without one: `loading.py`
    type-checks a venue's `rules` before any registry exists to inject.

    ``terms_by_kind`` is the channel for a venue whose rate depends on WHAT an instrument is. Give
    it and the charge is resolved per fill from the project's registered roster; omit it and each
    listing's own ``buy``/``sell`` are charged, which is right for a flat rate or a genuinely
    per-instrument fee schedule.

    An author writing a category-driven venue should reach for this rather than baking a rate into
    each ``TradeRule``. Baking it in means holding a second copy of a fact the project owns, and
    the two can disagree -- a fill then records the category the roster declared while the money
    follows the venue's own idea of it (issue 013). Nothing can detect that from the outside,
    because per-instrument rates are legitimate when they are not standing in for a category, so
    the defence is a reachable correct channel rather than a check.
    """
    return ExchangeRulesView(exchange_id, listings, registry, terms_by_kind)
