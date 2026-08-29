"""The project's instrument roster: what each traded id IS, declared once and read by every run.

A category answers no to both axes canon 2.8 splits an instrument's facts along -- a stock does
not become an ETF, and it is a stock on every venue -- so it belongs to the project rather than to
any venue. A venue reading that fact is right; a venue *declaring* it is the defect issue 008
names.

**The roster is a registered table, not a component.** A component is a thing Flow CALLS, which is
what `conformance`'s contract table encodes; a roster is a thing a run READS. Forcing it into
`ComponentKind` would buy the loader machinery at the price of an entry in that table whose answer
is nothing.

**One file per kind.** A parquet file carries exactly one schema, so a single file cannot hold
categories whose attributes differ. Keying the files by kind in the declaration keeps each schema
exact -- no nullable columns standing in for "not applicable" -- and makes adding an
attribute-bearing category additive: a new key and a new file, with every existing file unchanged.

**The `kind` column is duplicated into each file on purpose.** The declaration already states it
via the key, so the column is redundant; carrying it anyway lets registration check the two
against each other, which catches a file pointed at the wrong key. Redundancy bought for a check.

**Validation runs twice, and registration trusts nothing.** The exporter validates while building,
because a typed constructor refusing a bad value at creation is the cheapest place to catch it.
Registration validates again, because a hand-written parquet is an equally legitimate input and
must get the identical treatment. Producing a clean file is the user's responsibility; refusing a
dirty one is the framework's -- the same split `available_at` already states.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from vqapr.domain.instruments import INSTRUMENT_TYPES, Instrument, InstrumentKind, instrument

INSTRUMENT_ID_FIELD = "instrument_id"
KIND_FIELD = "kind"

REQUIRED_FIELDS: tuple[str, ...] = (INSTRUMENT_ID_FIELD, KIND_FIELD)
"""What every roster table must carry, whatever its category.

Both shipped categories are field-free today -- `kind` is a `ClassVar` on each `Instrument`
subclass -- so this is the whole schema. A category that carries its own facts (a future's
contract multiplier, an option's strike and right) adds columns to ITS file and leaves these two
required everywhere.
"""


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


def instrument_types() -> Mapping[InstrumentKind, type[Instrument]]:
    """The one door from a stored `kind` tag back to its class, re-exported for validation."""
    return INSTRUMENT_TYPES
