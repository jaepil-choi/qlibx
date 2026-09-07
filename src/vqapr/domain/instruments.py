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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
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


# ------------------------------------------------------------------------------------------
# roster.py, folded in (one-shape Step 7, record 162)
#
# The project's instrument roster: what each traded id IS, declared once and read by every run.
#
# A category answers no to both axes canon 2.8 splits an instrument's facts along -- a stock does
# not become an ETF, and it is a stock on every venue -- so it belongs to the project rather than to
# any venue. A venue reading that fact is right; a venue *declaring* it is the defect issue 008
# names.
#
# **The roster is a registered table, not a component.** A component is a thing Flow CALLS, which is
# what `conformance`'s contract table encodes; a roster is a thing a run READS. Forcing it into
# `ComponentKind` would buy the loader machinery at the price of an entry in that table whose answer
# is nothing.
#
# **One file per kind.** A parquet file carries exactly one schema, so a single file cannot hold
# categories whose attributes differ. Keying the files by kind in the declaration keeps each schema
# exact -- no nullable columns standing in for "not applicable" -- and makes adding an
# attribute-bearing category additive: a new key and a new file, with every existing file unchanged.
#
# **The `kind` column is duplicated into each file on purpose.** The declaration already states it
# via the key, so the column is redundant; carrying it anyway lets registration check the two
# against each other, which catches a file pointed at the wrong key. Redundancy bought for a check.
#
# **Validation runs twice, and registration trusts nothing.** The exporter validates while building,
# because a typed constructor refusing a bad value at creation is the cheapest place to catch it.
# Registration validates again, because a hand-written parquet is an equally legitimate input and
# must get the identical treatment. Producing a clean file is the user's responsibility; refusing a
# dirty one is the framework's -- the same split `available_at` already states.
# ------------------------------------------------------------------------------------------

INSTRUMENT_ID_FIELD = "instrument_id"
KIND_FIELD = "kind"


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One instrument's declared identity, as one row of a roster table."""

    instrument_id: str
    kind: InstrumentKind

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if not isinstance(self.kind, InstrumentKind):
            raise TypeError("kind must be an InstrumentKind")

    @property
    def row(self) -> dict[str, str]:
        """The row this entry writes, including the deliberately duplicated `kind`."""
        return {INSTRUMENT_ID_FIELD: self.instrument_id, KIND_FIELD: str(self.kind)}


@dataclass(frozen=True, slots=True)
class InstrumentRoster:
    """Every instrument a project has described, resolved and ready to read.

    Built by registration from the declared tables, and read fresh at run start. It is never
    compared against a previously recorded value: a roster GROWS as a matter of course -- a daily
    batch lists new tickers, issuers delist, a name is reclassified -- and a run refused because
    yesterday's roster differs from today's would refuse every morning. Issue 009 settles this:
    the digest is stated in the run record, never compared.
    """

    instruments: Mapping[str, Instrument]

    def __post_init__(self) -> None:
        if not isinstance(self.instruments, Mapping):
            raise TypeError("instruments must be a mapping")
        object.__setattr__(self, "instruments", dict(self.instruments))

    def __len__(self) -> int:
        return len(self.instruments)

    def __contains__(self, instrument_id: object) -> bool:
        return instrument_id in self.instruments

    def declares(self, instrument_id: str) -> bool:
        """Whether this roster describes `instrument_id` at all."""
        return instrument_id in self.instruments

    def instrument(self, instrument_id: str) -> Instrument:
        """The declared instrument, refusing an id nobody described.

        Raises rather than returning `None`. An id absent from every roster is an id nobody said
        anything about, and the whole point of this design is that such an id must not silently
        become a share -- *"the defect itself, written down rather than inferred"*. A caller that
        legitimately wants to ask without committing to an answer uses `declares`.
        """
        try:
            return self.instruments[instrument_id]
        except KeyError as error:
            raise KeyError(
                f"no registered instrument describes {instrument_id!r}; "
                "register it before trading it"
            ) from error

    def kind(self, instrument_id: str) -> InstrumentKind:
        return self.instrument(instrument_id).kind

    def notional(self, instrument_id: str, quantity: Decimal, price: Decimal) -> Decimal:
        """The traded value, routed through the instrument so a multiplier applies here too."""
        return self.instrument(instrument_id).notional(quantity, price)

    def quantity_for(self, instrument_id: str, value: Decimal, price: Decimal) -> Decimal:
        """The signed quantity reaching `value`; the exact inverse of `notional`."""
        return self.instrument(instrument_id).quantity_for(value, price)

    @property
    def histogram(self) -> dict[str, int]:
        """How many instruments of each declared category, for the registration receipt.

        The cheapest anti-sweep instrument in this design, and the only mechanical one, because it
        fires on the SUCCESS path: an author who declared 2,143 names and is shown a single bucket
        has been told so at registration rather than in a later failure. A uniform universe is a
        legitimate answer -- this only makes it impossible to give without noticing.
        """
        counts: dict[str, int] = {}
        for declared in self.instruments.values():
            counts[str(declared.kind)] = counts.get(str(declared.kind), 0) + 1
        return dict(sorted(counts.items()))


def build_roster(declared: Mapping[str, Mapping[str, str]]) -> InstrumentRoster:
    """Resolve `{kind: {instrument_id: kind}}` into a roster, refusing what it cannot describe.

    The nested shape mirrors the declaration: one group per kind-keyed table. Each group's key is
    checked against every row's own `kind` column, which is what makes the duplicated column worth
    carrying -- a table pointed at the wrong key is caught here rather than charging the wrong
    rate for the life of the project.
    """
    if not isinstance(declared, Mapping) or not declared:
        raise ValueError("a roster must declare at least one instrument table")
    resolved: dict[str, Instrument] = {}
    for declared_kind, rows in declared.items():
        expected = _kind(declared_kind)
        if not isinstance(rows, Mapping) or not rows:
            raise ValueError(f"instrument table {declared_kind!r} declares no instruments")
        for instrument_id, row_kind in rows.items():
            # Named with its instrument, not just its value. `_kind` alone reports "unknown
            # instrument kind 'crypto'", which tells an author of a three-thousand-row roster what
            # is wrong and not which row -- and a roster is exactly the artifact where finding the
            # row by hand is the expensive part. The four legal kinds still come from `_kind`.
            try:
                actual = _kind(row_kind)
            except ValueError as unknown:
                raise ValueError(
                    f"instrument {instrument_id!r} in the {declared_kind!r} table: {unknown}"
                ) from unknown
            if actual is not expected:
                raise ValueError(
                    f"instrument {instrument_id!r} sits in the {declared_kind!r} table but "
                    f"declares kind {row_kind!r}; the table key and the column must agree"
                )
            if instrument_id in resolved:
                raise ValueError(
                    f"instrument {instrument_id!r} is declared more than once; "
                    "one instrument has exactly one category"
                )
            resolved[instrument_id] = instrument(instrument_id, expected)
    return InstrumentRoster(resolved)


def _kind(value: object) -> InstrumentKind:
    """One spelling of the closed vocabulary, refusing anything outside it.

    `InstrumentKind` stays closed and package-owned. A user-invented category would be one a venue
    has no terms for, and expansion is a membership test -- so it would silently remove its
    instruments from the venue rather than refusing, which is the failure mode this package exists
    to eliminate.
    """
    if isinstance(value, InstrumentKind):
        return value
    try:
        return InstrumentKind(str(value))
    except ValueError as error:
        known = ", ".join(sorted(member.value for member in InstrumentKind))
        raise ValueError(
            f"unknown instrument kind {value!r}; declared kinds are {known}"
        ) from error


# ------------------------------------------------------------------------------------------
# roster_export.py, folded in (one-shape Step 7, record 162)
#
# Write a declared roster to the kind-keyed parquet tables registration reads.
#
# This is the half a user's `instruments.py` calls. That file is a **one-shot generation tool**: the
# user reads their own data with whatever tool they have, derives each instrument's category, and
# exports. The framework never registers, reads or fingerprints `instruments.py` itself -- its
# status is exactly that of `scripts/prepare_dev_data.py`, and registration begins at the clean file
# it produced.
#
# Why a script rather than a mapping in the declaration: a category is a typed value and a real
# universe is generated rather than typed. The motivating case is an instrument whose facts are not
# columns at all -- an option named `2603만기 삼성전자 콜옵션` carries its expiry, underlying and
# right inside a string, with no `right` column to map. No declaration syntax parses that; a few
# lines of the user's own Python do.
#
# The exporter validates while building, which is the first of the two validations this design runs.
# It is not the guarantee: registration re-validates the written file, because a hand-written
# parquet is an equally legitimate input.
# ------------------------------------------------------------------------------------------

def export_roster(
    universe: Mapping[str, str | InstrumentKind],
    directory: Path | str,
    *,
    stem: str = "instruments",
) -> dict[str, Path]:
    """Write one parquet per declared category and return `{kind: path}`.

    ``universe`` is the flat `{instrument_id: kind}` an author naturally builds. The split into
    per-kind tables happens here rather than in the author's head.

    Returns the mapping a declaration needs, so the emitted template can print exactly what to
    paste. Nothing is written for a category the universe does not use: an empty table would be a
    file whose only content is a schema, and a declaration pointing at one would claim the project
    trades a category it does not.
    """
    target = Path(directory)
    grouped: dict[InstrumentKind, list[RosterEntry]] = {}
    for instrument_id, declared in universe.items():
        entry = RosterEntry(instrument_id=str(instrument_id), kind=_kind(declared))
        grouped.setdefault(entry.kind, []).append(entry)
    if not grouped:
        raise ValueError("a roster must declare at least one instrument")

    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for kind, entries in sorted(grouped.items(), key=lambda item: str(item[0])):
        path = target / f"{stem}_{kind}.parquet"
        _write_table(path, entries)
        written[str(kind)] = path
    return written


def _write_table(path: Path, entries: Iterable[RosterEntry]) -> None:
    """One table, sorted by id so a re-export of an unchanged universe is byte-identical.

    Determinism matters here for the same reason it matters for any committed fixture: a digest
    that moves because a dictionary iterated differently would report a change nobody made.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = sorted((entry.row for entry in entries), key=lambda row: row[INSTRUMENT_ID_FIELD])
    if not rows:
        raise ValueError(f"instrument table {path.name!r} would be empty")
    table = pa.table(
        {
            INSTRUMENT_ID_FIELD: [row[INSTRUMENT_ID_FIELD] for row in rows],
            KIND_FIELD: [row[KIND_FIELD] for row in rows],
        }
    )
    pq.write_table(table, path)


def read_roster_table(path: Path | str) -> dict[str, str]:
    """Read one roster table back as `{instrument_id: kind}`, refusing a malformed one.

    Used by registration rather than by the exporter, and deliberately strict: the file may have
    been written by hand, by an older exporter, or by a script that got the schema wrong, and each
    of those must be refused with a message naming what is missing rather than producing a roster
    that is quietly short a column.
    """
    import pyarrow.parquet as pq

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"instrument table is missing: {source}")
    table = pq.read_table(source)
    columns = set(table.column_names)
    missing = [field for field in (INSTRUMENT_ID_FIELD, KIND_FIELD) if field not in columns]
    if missing:
        raise ValueError(
            f"instrument table {source.name!r} is missing required column(s) "
            f"{', '.join(missing)}; it must carry {INSTRUMENT_ID_FIELD} and {KIND_FIELD}"
        )
    ids = [str(value) for value in table.column(INSTRUMENT_ID_FIELD).to_pylist()]
    kinds = [str(value) for value in table.column(KIND_FIELD).to_pylist()]
    if not ids:
        raise ValueError(f"instrument table {source.name!r} declares no instruments")
    resolved: dict[str, str] = {}
    for instrument_id, kind in zip(ids, kinds, strict=True):
        if instrument_id in resolved and resolved[instrument_id] != kind:
            raise ValueError(
                f"instrument {instrument_id!r} appears twice in {source.name!r} with "
                f"different kinds ({resolved[instrument_id]!r} and {kind!r})"
            )
        resolved[instrument_id] = kind
    return resolved
