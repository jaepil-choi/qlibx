"""The account aggregate: the ledger it appends to, the snapshot folded from it, the marks that
value it, and the `Account` that is the only authority over all three.

Two things reach an account, by two doors. An entry changes the book -- a fill today; a dividend,
coupon, interest or funding payment once accrual exists -- and is appended with `Account.append`. A
mark values the book and changes nothing in it, and is recorded with `Account.mark`. A mark at an
instant without a fill appends no entry and does not move `account_version`: the version means
the account changed.

**One shape, an origin tag.** A fill, a dividend, a split and a subscription all move cash and
quantities in some combination of the same two cells, so a `LedgerEntry` is those two deltas plus
its `origin` and that origin's `detail`. The account checks what an account knows -- the state it
holds (version order), that the result is a valid account (cash never negative; no negative
position in a long-only book), that an entry is appended once -- and nothing else. Whether a fill's
cash is its price times its quantity less its cost is checked by whoever made the fill, and turning
a fill into entries is `domain/fill.py`'s, so this module never learns what its producers are.

**Not fill-only.** Encoding a dividend as a zero-quantity buy keeps the numbers right and corrupts
every count that reads fills as fills; the run's fill table is written from fill-origin entries
alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, field_validator

from vqapr.domain.instants import require_tz_aware

__all__ = [
    "FILL_ORIGIN",
    "Account",
    "AccountMark",
    "AccountMode",
    "AccountSnapshot",
    "AccountState",
    "LedgerEntry",
    "Mark",
    "MarkBatch",
    "MarkSummary",
    "PreparedAppend",
    "PreparedMark",
    "fold",
]


def _check_finite(value: Decimal, *, name: str) -> None:
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
        if not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        _check_finite(self.quantity, name="quantity")
        _check_finite(self.price, name="price")
        _check_finite(self.value, name="value")
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
        _check_finite(self.total_value, name="total_value")
        instruments = tuple(mark.instrument_id for mark in self.marks)
        if len(instruments) != len(set(instruments)):
            raise ValueError("a MarkBatch may contain each instrument only once")
        if self.total_value != sum((mark.value for mark in self.marks), Decimal("0")):
            raise ValueError("total_value must equal the sum of marks")

    def quantities(self) -> dict[str, Decimal]:
        """Return the complete immutable batch's explicitly marked quantities."""
        return {mark.instrument_id: mark.quantity for mark in self.marks}

    def summary(self) -> MarkSummary:
        """What outlives the batch once its rows are on the record."""
        return MarkSummary(total_value=self.total_value, marked=len(self.marks))


@dataclass(frozen=True, slots=True)
class MarkSummary:
    """A valuation's total and its count: what the run's evidence keeps of a `MarkBatch`.

    A batch is one `Mark` per held name, made at every instant of the market clock, and until
    record `224` every batch hung off the run's evidence and traces until the run ended --
    instants x names objects, 290 million for 3,000 names over a year of minutes. Nothing read
    them back: by the time a batch was made, its marks were `vqapr.account` rows. The evidence
    keeps this instead, and the batch is garbage as soon as the next instant's is committed.
    """

    total_value: Decimal
    marked: int

    def __post_init__(self) -> None:
        _check_finite(self.total_value, name="total_value")
        if isinstance(self.marked, bool) or not isinstance(self.marked, int) or self.marked < 0:
            raise ValueError("marked must be a non-negative count")


FILL_ORIGIN = "fill"
"""The origin of an entry a venue's fill made. The one origin the market clock produces today;
ACCRUE (design §7.3) is where the next ones will come from."""


def _finite(value: object, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One appended fact: what it changed, when, and what made it.

    `cash` and `positions` are DELTAS. Either may be zero -- a refused fill changes nothing and is
    still a fact the run has to be able to show afterwards (its `reason` is in `detail`), and a
    stock split changes quantities and no cash. `detail` is the origin's own: for a fill, the
    requested quantity, the price, the cost and the category it was charged as.
    """

    at: datetime
    cash: Decimal
    positions: Mapping[str, Decimal]
    origin: str
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_tz_aware(self.at, name="at")
        _finite(self.cash, name="cash")
        if not isinstance(self.positions, Mapping):
            raise TypeError("positions must be a mapping of instrument deltas")
        deltas: dict[str, Decimal] = {}
        for instrument_id, quantity in self.positions.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise ValueError("position instrument ids must be non-empty strings")
            deltas[instrument_id] = _finite(quantity, name=f"positions[{instrument_id!r}]")
        object.__setattr__(self, "positions", MappingProxyType(deltas))
        if not isinstance(self.origin, str) or not self.origin:
            raise ValueError("origin must be a non-empty string")
        if not isinstance(self.detail, Mapping):
            raise TypeError("detail must be a mapping")
        object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))


def _decimal(value: object, *, name: str, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


class AccountSnapshot(BaseModel):
    """A value snapshot that cannot expose or alias mutable Account state.

    Two doors. The constructor validates: it is what a run declaration, a test and the CLI
    hand in, and strict pydantic refuses a `bool` version, a `float` cash or an `int` quantity
    rather than coercing them. `trusted` does not: it is for the one place that derives the next
    snapshot from a snapshot already validated, once per commit, on the hot path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: int
    cash: Decimal
    positions: Mapping[str, Decimal]

    def __init__(self, version: int, cash: Decimal, positions: Mapping[str, Decimal]) -> None:
        # Positional as well as keyword: `AccountSnapshot(0, Decimal("100"), {})` is how a run
        # declaration and every test spell it.
        super().__init__(version=version, cash=cash, positions=positions)

    @classmethod
    def trusted(
        cls, *, version: int, cash: Decimal, positions: Mapping[str, Decimal]
    ) -> AccountSnapshot:
        """The engine's door: a snapshot from values it derived from a validated one.

        No validation runs. The caller guarantees what the constructor would have checked --
        a non-negative version and cash, finite quantities, and no zero position -- because it
        computed them from a snapshot that already passed and from fills the batch already
        validated. The mapping is copied into a read-only view so the result aliases nothing.
        """
        return cls.model_construct(
            version=version, cash=cash, positions=MappingProxyType(dict(positions))
        )

    def value(self, prices: Mapping[str, Decimal]) -> MarkBatch:
        """This book at `prices`: every holding with a price, quantity times price, by name.

        The snapshot multiplies its own holdings, so a valuation can only value what is held, at
        the held quantity -- what `Account.mark` once had to check of a batch built elsewhere is
        true by construction (record `276`). A holding with no price leaves the valuation and
        stays in the book: `domain/valuation.py::select_prices` has already carried a halted
        name's last price forward, so a name missing here is one the venue never priced, and there
        is no honest number to put in the denominator.
        """
        marks = [
            Mark(instrument, quantity, prices[instrument], quantity * prices[instrument])
            for instrument, quantity in sorted(self.positions.items())
            if quantity != 0 and instrument in prices
        ]
        return MarkBatch(tuple(marks), sum((mark.value for mark in marks), Decimal("0")))

    @field_validator("version")
    @classmethod
    def _non_negative_version(cls, value: int) -> int:
        if value < 0:
            raise ValueError("version must be non-negative")
        return value

    @field_validator("cash")
    @classmethod
    def _non_negative_cash(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("cash must be non-negative")
        return value

    @field_validator("positions")
    @classmethod
    def _held(cls, value: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
        # After pydantic has checked the keys are strings and the values finite Decimals: an
        # empty id is still a string, and a zero quantity is not a position.
        normalized: dict[str, Decimal] = {}
        for instrument_id, quantity in value.items():
            if not instrument_id:
                raise ValueError("position instrument ids must be non-empty strings")
            if quantity != 0:
                normalized[instrument_id] = quantity
        return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class AccountMark:
    """The complete valuation published for one Account snapshot at one instant.

    A mark is identified by **when it was taken**, not by the account version it values. An
    occurrence that trades nothing still values the book, so several marks can belong to one
    account version, and their order is the order they were taken in.
    """

    account_version: int
    marks: MarkBatch
    nav: Decimal
    marked_at: datetime | None = None
    observed_at_by_instrument: Mapping[str, datetime] | None = None
    """When each carried price was observed, which is not always when the mark was taken.

    A halted name keeps the instant its last real price was published, so the next mark can carry
    it forward without the gap silently resetting to now.
    """

    def __post_init__(self) -> None:
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(self.marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")
        _decimal(self.nav, name="nav")
        if self.marked_at is not None:
            require_tz_aware(self.marked_at, name="marked_at")
        if self.observed_at_by_instrument is not None:
            if not isinstance(self.observed_at_by_instrument, Mapping):
                raise TypeError("observed_at_by_instrument must be a mapping")
            observed = {}
            for instrument, instant in self.observed_at_by_instrument.items():
                if not isinstance(instrument, str) or not instrument:
                    raise ValueError("observed_at instrument ids must be non-empty strings")
                observed[instrument] = require_tz_aware(instant, name="observed_at")
            object.__setattr__(self, "observed_at_by_instrument", MappingProxyType(observed))


@dataclass(frozen=True, slots=True)
class AccountState:
    """The committed account as a run holds it: the fold, the mark window, the last append.

    Design §5.1: *the real ledger is the record's parquet; this is the ledger's cached fold plus
    the buffer awaiting publication.* `snapshot` is the fold of every entry ever appended;
    `ledger` is the entries the LAST append made -- published to `vqapr.fill` and then dropped,
    so the resident state never grows with the run; `marks` is the window of marks a consumer
    declared it reads (`Account.retained_marks`), oldest first, which is a property of this run's
    memory and not of the ledger.

    What is checked here is what a window can be checked for in its own length: marks in version
    and instant order, and the newest mark valuing this snapshot. Whether an entry may be appended
    is the `Account`'s question (record `211`).
    """

    snapshot: AccountSnapshot
    marks: tuple[AccountMark, ...] = ()
    ledger: tuple[LedgerEntry, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AccountSnapshot):
            raise TypeError("snapshot must be an AccountSnapshot")
        if not isinstance(self.marks, tuple) or any(
            not isinstance(mark, AccountMark) for mark in self.marks
        ):
            raise TypeError("marks must be a tuple of AccountMark")
        if not isinstance(self.ledger, tuple) or any(
            not isinstance(entry, LedgerEntry) for entry in self.ledger
        ):
            raise TypeError("ledger must be a tuple of LedgerEntry")
        if self.marks:
            versions = tuple(mark.account_version for mark in self.marks)
            # Non-decreasing, not strictly increasing: a market-clock instant that trades nothing
            # marks the book without advancing the account version, so one version can carry
            # several marks. What must never happen is a mark for an earlier version arriving
            # later.
            if any(later < earlier for earlier, later in pairwise(versions)):
                raise ValueError("mark versions must not decrease")
            instants = tuple(mark.marked_at for mark in self.marks if mark.marked_at is not None)
            if any(later <= earlier for earlier, later in pairwise(instants)):
                raise ValueError("mark instants must be strictly increasing")
            latest = self.marks[-1]
            if latest.account_version > self.snapshot.version:
                raise ValueError("latest mark cannot belong to a future Account snapshot")
            if (
                latest.account_version == self.snapshot.version
                and latest.nav != self.snapshot.cash + latest.marks.total_value
            ):
                raise ValueError("latest mark NAV must match the current Account snapshot")

    @property
    def latest_mark(self) -> AccountMark | None:
        return self.marks[-1] if self.marks else None


def fold(snapshot: AccountSnapshot, entries: Iterable[LedgerEntry]) -> AccountSnapshot:
    """The book after appending `entries` to `snapshot`: one version later, deltas applied.

    Arithmetic only (design §5.1: the ledger's incremental fold). A zero resulting quantity
    leaves the book -- a position is a non-zero holding; whether the result is a *valid* account
    -- cash not negative, no short in a long-only book -- is the `Account`'s question, asked once
    on the folded result rather than on every delta.
    """
    cash = snapshot.cash
    positions = dict(snapshot.positions)
    for entry in entries:
        if not isinstance(entry, LedgerEntry):
            raise TypeError("entries must be LedgerEntry values")
        cash += entry.cash
        for instrument_id, delta in entry.positions.items():
            quantity = positions.get(instrument_id, Decimal(0)) + delta
            if quantity == 0:
                positions.pop(instrument_id, None)
            else:
                positions[instrument_id] = quantity
    return AccountSnapshot.trusted(version=snapshot.version + 1, cash=cash, positions=positions)


class AccountMode(StrEnum):
    """The sole account-level position constraint."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


@dataclass(frozen=True, slots=True)
class PreparedAppend:
    """Ledger entries the Account has agreed to append, and the state they fold to.

    Not yet an Account mutation: the run state publishes `next_state` as its root, and only then
    does `commit_append` install it. `next_state` carries the entries it was made by and the mark
    window it inherited; the record's fill table is written from those entries.
    """

    source: AccountState
    entries: tuple[LedgerEntry, ...]
    next_state: AccountState

    def __post_init__(self) -> None:
        if not isinstance(self.source, AccountState):
            raise TypeError("source must be an AccountState")
        if not isinstance(self.entries, tuple) or any(
            not isinstance(entry, LedgerEntry) for entry in self.entries
        ):
            raise TypeError("entries must be a tuple of LedgerEntry")
        if not isinstance(self.next_state, AccountState):
            raise TypeError("next_state must be an AccountState")
        if self.next_state.snapshot.version != self.source.snapshot.version + 1:
            raise ValueError("an append advances the account version by exactly one")
        if self.next_state.ledger != self.entries:
            raise ValueError("next_state must carry exactly the appended entries")
        if self.next_state.marks != self.source.marks:
            raise ValueError("an append changes no mark")

    @property
    def expected_version(self) -> int:
        return self.source.snapshot.version

    @property
    def next_snapshot(self) -> AccountSnapshot:
        return self.next_state.snapshot


@dataclass(frozen=True, slots=True)
class PreparedMark:
    """A mark the Account has agreed to append to the state it values."""

    source: AccountState
    mark: AccountMark
    next_state: AccountState

    def __post_init__(self) -> None:
        if not isinstance(self.source, AccountState):
            raise TypeError("source must be an AccountState")
        if not isinstance(self.mark, AccountMark):
            raise TypeError("mark must be an AccountMark")
        if not isinstance(self.next_state, AccountState):
            raise TypeError("next_state must be an AccountState")
        if self.next_state.snapshot != self.source.snapshot:
            raise ValueError("a mark changes no account snapshot")
        if self.next_state.ledger != self.source.ledger:
            raise ValueError("a mark changes no ledger entry")
        if self.next_state.latest_mark is not self.mark:
            raise ValueError("next_state must end with the appended mark")
        if self.mark.account_version != self.source.snapshot.version:
            raise ValueError("a mark values the current account snapshot")


class Account:
    """Owns append permission; `AcceptedRunState` owns publication."""

    def __init__(self, *, mode: AccountMode, retained_marks: int = 1) -> None:
        if not isinstance(mode, AccountMode):
            raise TypeError("mode must be an AccountMode")
        if isinstance(retained_marks, bool) or not isinstance(retained_marks, int):
            raise TypeError("retained_marks must be an integer")
        if retained_marks < 1:
            raise ValueError("an Account must retain at least its current mark")
        self._mode = mode
        # The mark WINDOW: how many marks stay resident, a property of this run's memory and not
        # of the ledger (design §5.1). One unless a consumer declared it reads more; the full
        # series goes to the recorder.
        self._retained_marks = retained_marks
        self._state: AccountState | None = None

    @property
    def mode(self) -> AccountMode:
        return self._mode

    @property
    def state(self) -> AccountState:
        """Return the immutable committed authority, never a mutable backing store."""
        if self._state is None:
            raise RuntimeError("Account has not been bound to an initial state")
        return self._state

    def bind(self, state: AccountState) -> None:
        """Bind this Account to the sole initial state before execution begins."""
        if not isinstance(state, AccountState):
            raise TypeError("state must be an AccountState")
        if self._state is not None:
            raise RuntimeError("Account is already bound")
        self._state = state

    def append(
        self, state: AccountState, entries: tuple[LedgerEntry, ...], *, expected_version: int
    ) -> PreparedAppend:
        """May these entries go after this state? Version order and a valid result, nothing else.

        The producer proved each entry's own arithmetic. What is proved here is what only the
        ledger can: that `state` is the version the caller thinks it is, and that the folded book
        is an account -- cash not negative, and no short position in a long-only account.
        """
        if not isinstance(state, AccountState):
            raise TypeError("state must be an AccountState")
        if not isinstance(entries, tuple) or any(
            not isinstance(entry, LedgerEntry) for entry in entries
        ):
            raise TypeError("entries must be a tuple of LedgerEntry")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise TypeError("expected_version must be an integer")
        if expected_version != state.snapshot.version:
            raise ValueError("expected_version does not match the current account version")
        folded = fold(state.snapshot, entries)
        if folded.cash < 0:
            raise ValueError("fill batch would make cash negative")
        if self._mode is AccountMode.LONG_ONLY and any(
            quantity < 0 for quantity in folded.positions.values()
        ):
            raise ValueError("fill batch would create a short position in a long-only account")
        return PreparedAppend(
            source=state,
            entries=entries,
            # Published, not retained: the entries this append made go to the record's fill
            # table, and the state keeps only them, so the resident ledger stops growing for the
            # life of the run while every entry still reaches parquet.
            next_state=AccountState(snapshot=folded, marks=state.marks, ledger=entries),
        )

    def mark(
        self,
        state: AccountState,
        prices: Mapping[str, Decimal],
        *,
        marked_at: datetime | None = None,
        observed_at: Mapping[str, datetime] | None = None,
    ) -> PreparedMark:
        """Value what this state holds at `prices`, and agree to append that mark after it.

        One door for both market-clock cases (design §3.1): the mark after a fill and the mark of
        a held book differ only in what the ledger did just before, which is not the mark's
        concern. The caller chooses the prices (`domain/valuation.py`); the account multiplies
        its own holdings (`AccountSnapshot.value`). The account does not change; the window
        slides.
        """
        if not isinstance(state, AccountState):
            raise TypeError("state must be an AccountState")
        if not isinstance(prices, Mapping):
            raise TypeError("prices must be a mapping of instrument to price")
        current = state.snapshot
        marks = current.value(prices)
        mark = AccountMark(
            account_version=current.version,
            marks=marks,
            nav=current.cash + marks.total_value,
            marked_at=marked_at,
            observed_at_by_instrument=observed_at,
        )
        return PreparedMark(
            source=state,
            mark=mark,
            next_state=AccountState(
                snapshot=current,
                marks=(*state.marks, mark)[-self._retained_marks :],
                ledger=state.ledger,
            ),
        )

    def commit_append(self, prepared: PreparedAppend) -> AccountState:
        """Infallibly install a previously agreed append after optimistic checking."""
        if not isinstance(prepared, PreparedAppend):
            raise TypeError("prepared must be a PreparedAppend")
        if self.state != prepared.source:
            raise RuntimeError("Account optimistic conflict")
        self._state = prepared.next_state
        return self._state

    def commit_mark(self, prepared: PreparedMark) -> AccountState:
        """Infallibly install a previously agreed mark after optimistic checking."""
        if not isinstance(prepared, PreparedMark):
            raise TypeError("prepared must be a PreparedMark")
        if self.state != prepared.source:
            raise RuntimeError("Account optimistic conflict")
        self._state = prepared.next_state
        return self._state
