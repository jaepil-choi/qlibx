"""Versioned Account authority for closed Academic execution results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from vqapr.account.snapshot import AccountMark, AccountSnapshot, AccountState
from vqapr.exchange.fills import Fill, FillBatch
from vqapr.valuation.marks import MarkBatch


class AccountMode(StrEnum):
    """The sole account-level position constraint."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """Append-only record of one fill included in an account transition."""

    version: int
    fill: Fill


@dataclass(frozen=True, slots=True)
class PreparedAccountFill:
    """A validated fill candidate that is not an Account mutation."""

    expected_version: int
    source: AccountState
    fill_batch: FillBatch
    next_snapshot: AccountSnapshot
    journal_entries: tuple[JournalEntry, ...]

    def __post_init__(self) -> None:
        if isinstance(self.expected_version, bool) or not isinstance(self.expected_version, int):
            raise TypeError("expected_version must be an integer")
        if self.expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        if not isinstance(self.source, AccountState):
            raise TypeError("source must be an AccountState")
        if self.source.snapshot.version != self.expected_version:
            raise ValueError("source version must match expected_version")
        if not isinstance(self.fill_batch, FillBatch):
            raise TypeError("fill_batch must be a FillBatch")
        if self.fill_batch.account_version_seen != self.expected_version:
            raise ValueError("fill_batch version must match expected_version")
        if not isinstance(self.next_snapshot, AccountSnapshot):
            raise TypeError("next_snapshot must be an AccountSnapshot")
        if self.next_snapshot.version != self.expected_version + 1:
            raise ValueError("next_snapshot version must advance expected_version by one")
        if not isinstance(self.journal_entries, tuple) or any(
            not isinstance(entry, JournalEntry) for entry in self.journal_entries
        ):
            raise TypeError("journal_entries must be a tuple of JournalEntry")
        if any(entry.version != self.next_snapshot.version for entry in self.journal_entries):
            raise ValueError("journal entries must have the committed version")


@dataclass(frozen=True, slots=True)
class PreparedAccountTransition:
    """A complete fill-and-mark candidate suitable for one root publication."""

    fill: PreparedAccountFill
    next_state: AccountState

    def __post_init__(self) -> None:
        if not isinstance(self.fill, PreparedAccountFill):
            raise TypeError("fill must be a PreparedAccountFill")
        if not isinstance(self.next_state, AccountState):
            raise TypeError("next_state must be an AccountState")
        if self.next_state.snapshot != self.fill.next_snapshot:
            raise ValueError("next_state must publish the prepared fill snapshot")
        if self.next_state.fill_history != (
            *self.fill.source.fill_history,
            *self.fill.journal_entries,
        ):
            raise ValueError("next_state must contain exactly the prepared fill history")
        if self.next_state.mark_history[:-1] != self.fill.source.mark_history:
            raise ValueError("next_state must preserve the published mark history")
        latest_mark = self.next_state.latest_mark
        if latest_mark is None or latest_mark.account_version != self.fill.next_snapshot.version:
            raise ValueError("next_state must append a mark for the prepared snapshot")


class Account:
    """Owns Account transition validation; AcceptedRunState owns publication."""

    def __init__(self, *, mode: AccountMode) -> None:
        if not isinstance(mode, AccountMode):
            raise TypeError("mode must be an AccountMode")
        self._mode = mode
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

    def prepare_fill(
        self, state: AccountState, fill_batch: FillBatch, *, expected_version: int
    ) -> PreparedAccountFill:
        """Validate a complete fill candidate without retaining mutable Account state."""
        if not isinstance(state, AccountState):
            raise TypeError("state must be an AccountState")
        if not isinstance(fill_batch, FillBatch):
            raise TypeError("fill_batch must be a FillBatch")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise TypeError("expected_version must be an integer")
        current = state.snapshot
        if expected_version != current.version:
            raise ValueError("expected_version does not match the current account version")
        if fill_batch.account_version_seen != expected_version:
            raise ValueError("fill_batch account_version_seen does not match expected_version")

        next_cash = current.cash
        next_positions = dict(current.positions)
        for fill in fill_batch.fills:
            # Fill validates finite values and requires a price for every dealt quantity.
            if fill.dealt_quantity == 0:
                continue
            assert fill.price is not None
            next_cash -= fill.dealt_quantity * fill.price
            quantity = next_positions.get(fill.instrument_id, Decimal(0)) + fill.dealt_quantity
            if quantity == 0:
                next_positions.pop(fill.instrument_id, None)
            else:
                next_positions[fill.instrument_id] = quantity

        if next_cash < 0:
            raise ValueError("fill batch would make cash negative")
        if self._mode is AccountMode.LONG_ONLY and any(
            quantity < 0 for quantity in next_positions.values()
        ):
            raise ValueError("fill batch would create a short position in a long-only account")

        next_snapshot = AccountSnapshot(
            version=current.version + 1,
            cash=next_cash,
            positions=next_positions,
        )
        return PreparedAccountFill(
            expected_version=expected_version,
            source=state,
            fill_batch=fill_batch,
            next_snapshot=next_snapshot,
            journal_entries=tuple(
                JournalEntry(version=next_snapshot.version, fill=fill) for fill in fill_batch.fills
            ),
        )

    def prepare_mark(
        self, fill: PreparedAccountFill, marks: MarkBatch, *, provenance: object
    ) -> PreparedAccountTransition:
        """Validate the required post-fill valuation before any root is published."""
        if not isinstance(fill, PreparedAccountFill):
            raise TypeError("fill must be a PreparedAccountFill")
        if not isinstance(marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")
        marked_positions = marks.quantities()
        if marked_positions != dict(fill.next_snapshot.positions):
            raise ValueError("marks must exactly cover the filled account positions")
        mark = AccountMark(
            account_version=fill.next_snapshot.version,
            marks=marks,
            nav=fill.next_snapshot.cash + marks.total_value,
            provenance=provenance,
        )
        return PreparedAccountTransition(
            fill=fill,
            next_state=AccountState(
                snapshot=fill.next_snapshot,
                mark_history=(*fill.source.mark_history, mark),
                fill_history=(*fill.source.fill_history, *fill.journal_entries),
            ),
        )

    def commit_fill(self, prepared: PreparedAccountFill) -> AccountState:
        """Infallibly install a previously validated fill after optimistic checking."""
        if not isinstance(prepared, PreparedAccountFill):
            raise TypeError("prepared must be a PreparedAccountFill")
        if self.state != prepared.source:
            raise RuntimeError("Account optimistic conflict")
        self._state = AccountState(
            snapshot=prepared.next_snapshot,
            mark_history=prepared.source.mark_history,
            fill_history=(*prepared.source.fill_history, *prepared.journal_entries),
        )
        return self._state

    def commit_mark(self, prepared: PreparedAccountTransition) -> AccountState:
        """Infallibly install a previously validated valuation after optimistic checking."""
        if not isinstance(prepared, PreparedAccountTransition):
            raise TypeError("prepared must be a PreparedAccountTransition")
        if self.state.snapshot != prepared.fill.next_snapshot:
            raise RuntimeError("Account optimistic conflict")
        if self.state.fill_history != prepared.next_state.fill_history:
            raise RuntimeError("Account optimistic conflict")
        self._state = prepared.next_state
        return self._state
