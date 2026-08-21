"""Venue-independent instrument identity.

Canon 2.8 splits an instrument's facts along two axes: does it change over time, and does it
change with the venue. ``kind`` answers no to both -- a stock does not become an ETF, and it is a
stock on every venue -- so it lives here in ``domain`` and not in ``exchange``. Quantity units and
permitted sides answer yes to the venue axis and belong to ``ListingRule``; tradability and price
answer yes to the time axis and belong to the execution table.

This module is the reason a cost band can name a *kind* instead of an instrument id. KRX exempts
ETFs from the sale tax stocks pay, and that exemption is a rule about a category, not about a list
of tickers -- see ``vqapr.exchange.costs``.

The four categories are the ones ``UC-ACADEMIC-001`` names:

    Stock                        a common share
    ETF                          an exchange-traded fund, taxed differently on some venues
    tracking-only Index          an index level, referenced rather than held
    synthetic-unit-price Factor  a factor held against a synthetic unit price

**Tradability is not here, deliberately.** Canon 6.2: *"거래 가능 여부를 넣지 않는 이유 --
``permitted_sides``가 이미 표현한다. 같은 사실을 두 곳에 두지 않는다"*. Whether an instrument can
be traded is a venue judgement, and the same instrument gets different answers on different venues:
a factor is tradable on an academic venue and not listed at all on KRX. A venue says so by
declaring a ``ListingRule`` whose access is ``NONE``, or by not listing it.

Nor is a category "synthetic" or "real". That axis exists -- an ETF's NAV is computed from a
basket, a KTB futures settlement price is computed from a deliverable basket, an index level is
computed from constituents -- but it describes **how a price is formed**, not whether the thing can
be filled. A KTB future is entirely tradable and its reference price is entirely synthetic. The
package therefore never branches on it.

Adding an instrument category
-----------------------------
``kind`` is a closed discriminator and each category is its own class, so a new category is
additive: add the enum member, add the class, register it below. Nothing that already exists is
edited. Categories with their own facts are exactly where those facts belong:

    FUTURE   expiry, contract multiplier, settlement currency
    BOND     maturity, coupon, accrual convention

``notional`` and ``quantity_for`` are the inverse pair every money-to-quantity conversion in the
package routes through, so a category whose contract size is not one share overrides two methods
here rather than editing order planning and each venue. They are declared on the base precisely so
that the override site exists before it is needed.

**Not implemented, and therefore not claimed**

- Margin and collateral, mark-to-market settlement, expiry rollover, and any cash flow that is not
  a fill. Whether a position consumes its full notional or a margin deposit is an *account* fact
  (canon 2.8: negative cash is decided by the account type), so a leveraged category needs an
  account mode alongside the class added here. Neither exists yet.
- **A Factor's synthetic unit price is not synthesised here.** The category says a factor is held
  against a unit price; producing that series -- a cumulative return index, however normalised --
  is the user's registration, published through the execution table like any other price. The
  package does not invent it, because the normalisation is a research decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar


class InstrumentKind(StrEnum):
    """The closed vocabulary a cost band is allowed to select on.

    A closed enum rather than a free string: a rule that selects on a misspelled category would
    otherwise match nothing and charge nothing, which is the silent failure this package refuses.
    """

    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"
    FACTOR = "factor"


def base_notional(quantity: Decimal, price: Decimal) -> Decimal:
    """The traded value of ``quantity`` at ``price`` when one unit is one unit.

    Defined once so that the no-multiplier case has exactly one spelling, shared by
    :meth:`Instrument.notional` and by order planning when a venue declares no instruments.
    """
    return abs(quantity) * price


def base_quantity_for(value: Decimal, price: Decimal) -> Decimal:
    """The signed quantity whose notional is ``value``, the inverse of :func:`base_notional`."""
    return value / price


@dataclass(frozen=True, slots=True)
class Instrument:
    """What an instrument is, independent of where it trades.

    Carries no ``exchange_id``. The same instrument may list on several venues with different
    quantity units, and stamping a venue here would force it to be declared once per venue,
    breaking the single fact that it is one instrument (canon 6.2).
    """

    instrument_id: str

    kind: ClassVar[InstrumentKind]

    def __post_init__(self) -> None:
        if type(self) is Instrument:
            raise TypeError("Instrument is a base category; construct a concrete kind")
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")

    def notional(self, quantity: Decimal, price: Decimal) -> Decimal:
        """The absolute traded value of ``quantity`` at ``price``.

        A category whose contract is not one unit of the quoted price -- a future with a
        contract multiplier, say -- overrides this.
        """
        return base_notional(quantity, price)

    def quantity_for(self, value: Decimal, price: Decimal) -> Decimal:
        """The signed quantity reaching ``value`` of exposure at ``price``.

        The exact inverse of :meth:`notional`; a category that overrides one must override both.
        """
        return base_quantity_for(value, price)

    @property
    def declaration_identity(self) -> tuple[str, str]:
        return (self.instrument_id, self.kind.value)


@dataclass(frozen=True, slots=True)
class StockInstrument(Instrument):
    """A common share. One unit of quantity is one share of the quoted price."""

    kind: ClassVar[InstrumentKind] = InstrumentKind.STOCK


@dataclass(frozen=True, slots=True)
class EtfInstrument(Instrument):
    """An exchange-traded fund. Trades share-like, and is taxed differently on some venues."""

    kind: ClassVar[InstrumentKind] = InstrumentKind.ETF


@dataclass(frozen=True, slots=True)
class IndexInstrument(Instrument):
    """An index level: referenced rather than held.

    An index level is data -- canon 4.1 registers it as an ordinary series under a synthetic id.
    The category exists because a portfolio system has to *name* things it does not hold: a
    benchmark is compared against, and a derivative's underlying is referenced by its contract.
    Naming it as an instrument is what lets a venue state its judgement about it at all.

    Nothing here says it cannot be traded. A venue that does not trade it either omits it from its
    listings or lists it with no permitted side; a venue that trades an index product lists that
    product. That judgement is the venue's, on the venue's own terms.
    """

    kind: ClassVar[InstrumentKind] = InstrumentKind.INDEX


@dataclass(frozen=True, slots=True)
class FactorInstrument(Instrument):
    """A factor held against a synthetic unit price.

    An academic study builds a book out of factors the way an equity study builds one out of
    shares: a weight becomes a quantity at a price, fills, and is marked. The unit price is
    synthetic, but every step downstream is the ordinary one, which is the point -- a factor book
    measured by a separate return-weighting path would not be measured by the account at all.
    """

    kind: ClassVar[InstrumentKind] = InstrumentKind.FACTOR


INSTRUMENT_TYPES: Mapping[InstrumentKind, type[Instrument]] = {
    StockInstrument.kind: StockInstrument,
    EtfInstrument.kind: EtfInstrument,
    IndexInstrument.kind: IndexInstrument,
    FactorInstrument.kind: FactorInstrument,
}
"""The one door from a stored ``kind`` tag back to its class."""


def instrument(instrument_id: str, kind: InstrumentKind | str) -> Instrument:
    """Build the instrument for a declared ``kind``, refusing an unknown category."""
    try:
        resolved = InstrumentKind(kind)
    except ValueError as error:
        known = ", ".join(sorted(member.value for member in InstrumentKind))
        raise ValueError(f"unknown instrument kind {kind!r}; declared kinds are {known}") from error
    return INSTRUMENT_TYPES[resolved](instrument_id)


def instruments(kinds: Mapping[str, InstrumentKind | str]) -> dict[str, Instrument]:
    """Build a venue roster from an ``instrument_id -> kind`` declaration."""
    if not isinstance(kinds, Mapping):
        raise TypeError("kinds must be a mapping of instrument_id to InstrumentKind")
    return {instrument_id: instrument(instrument_id, kind) for instrument_id, kind in kinds.items()}
