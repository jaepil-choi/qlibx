"""The Account: the authority that appends to the ledger, and nothing else.

Design §5.1: *"`Account` = 권한. '이 항목을 이 원장 뒤에 붙일 수 있는가'만 판단하고 붙인다."* Two
things may be appended -- ledger entries, which change the book, and marks, which value it -- and
for each the Account asks the same three questions: is this the state I hold (version order), is
what results a valid account (cash not negative; no short in a long-only book; a mark that values
what is held), and is it being appended once. Everything an origin knows about its own entry --
that a fill's cash is its price times its quantity less its cost -- was checked by the producer
that made it (§5.2: *the ledger checks what the ledger knows*).

Record `211`: this is what `prepare_fill` / `prepare_mark` / `prepare_valuation` and their three
`Prepared*` types collapsed into. Those carried three hand-written statements of "what must not
change" and a `_appends_one_mark` that compared tails to allow for retention; the invariant is now
one, stated once, and retention is the Account's own window rather than a property the ledger has
to be forgiven for.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from vqapr.domain.account_state import AccountMark, AccountSnapshot, AccountState, fold
from vqapr.domain.ledger import LedgerEntry
from vqapr.domain.values import MarkBatch


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


def _require_marks_within(marks: MarkBatch, snapshot: AccountSnapshot) -> None:
    """Marks must be a subset of the held positions, at the held quantities.

    Not an exact cover. A holding the venue cannot price at this instant carries no mark and
    contributes nothing to NAV, which is the position record 020 already took for the execution
    path: valuing it from a stale quote would put an invented number in the denominator every
    later weight is converted against. The position itself stays in the snapshot, so it is never
    silently dropped from the book -- only from the valuation.
    """
    marked = marks.quantities()
    held = dict(snapshot.positions)
    unknown = tuple(sorted(set(marked) - set(held)))
    if unknown:
        raise ValueError(f"marks contain instruments the account does not hold: {unknown}")
    mismatched = tuple(
        sorted(
            instrument for instrument, quantity in marked.items() if held[instrument] != quantity
        )
    )
    if mismatched:
        raise ValueError(f"marks must value the held quantity for {mismatched}")


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
        marks: MarkBatch,
        *,
        provenance: object,
        marked_at: datetime | None = None,
        observed_at: Mapping[str, datetime] | None = None,
    ) -> PreparedMark:
        """May this valuation go after this state? It must value what the state holds.

        One door for both market-clock cases (design §3.1): the mark after a fill and the mark of
        a held book differ only in what the ledger did just before, which is not the mark's
        concern. The account does not change; the window slides.
        """
        if not isinstance(state, AccountState):
            raise TypeError("state must be an AccountState")
        if not isinstance(marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")
        current = state.snapshot
        _require_marks_within(marks, current)
        mark = AccountMark(
            account_version=current.version,
            marks=marks,
            nav=current.cash + marks.total_value,
            provenance=provenance,
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


__all__ = ["Account", "AccountMode", "PreparedAppend", "PreparedMark"]
