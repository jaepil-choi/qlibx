"""Versioned Account authority for closed Academic execution results."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from vqapr.account.snapshot import AccountSnapshot
from vqapr.exchange.fills import Fill, FillBatch


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
class PreparedAccountCommit:
    """A fully validated transition that has not yet been published."""

    expected_version: int
    next_snapshot: AccountSnapshot
    journal_entries: tuple[JournalEntry, ...]

    def __post_init__(self) -> None:
        if isinstance(self.expected_version, bool) or not isinstance(self.expected_version, int):
            raise TypeError("expected_version must be an integer")
        if self.expected_version < 0:
            raise ValueError("expected_version must be non-negative")
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


class Account:
    """Owns validation and atomic publication of fill-driven state transitions."""

    def __init__(self, snapshot: AccountSnapshot, *, mode: AccountMode) -> None:
        if not isinstance(snapshot, AccountSnapshot):
            raise TypeError("snapshot must be an AccountSnapshot")
        if not isinstance(mode, AccountMode):
            raise TypeError("mode must be an AccountMode")
        self._mode = mode
        self._snapshot = AccountSnapshot(snapshot.version, snapshot.cash, snapshot.positions)
        self._journal: list[JournalEntry] = []
        self._history: list[AccountSnapshot] = [self.snapshot()]
        self._prepared: PreparedAccountCommit | None = None

    @property
    def mode(self) -> AccountMode:
        return self._mode

    @property
    def journal(self) -> tuple[JournalEntry, ...]:
        return tuple(self._journal)

    @property
    def history(self) -> tuple[AccountSnapshot, ...]:
        return tuple(self._history)

    def snapshot(self) -> AccountSnapshot:
        """Return a fresh detached immutable value, never internal Account state."""
        current = self._snapshot
        return AccountSnapshot(current.version, current.cash, current.positions)

    def prepare_commit(
        self, fill_batch: FillBatch, *, expected_version: int
    ) -> PreparedAccountCommit:
        """Validate a complete fill batch without mutating the Account."""
        if not isinstance(fill_batch, FillBatch):
            raise TypeError("fill_batch must be a FillBatch")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise TypeError("expected_version must be an integer")
        current = self._snapshot
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
        prepared = PreparedAccountCommit(
            expected_version=expected_version,
            next_snapshot=next_snapshot,
            journal_entries=tuple(
                JournalEntry(version=next_snapshot.version, fill=fill) for fill in fill_batch.fills
            ),
        )
        self._prepared = prepared
        return prepared

    def commit(self, prepared: PreparedAccountCommit) -> AccountSnapshot:
        """Publish exactly the transition produced by the latest successful preparation."""
        if not isinstance(prepared, PreparedAccountCommit):
            raise TypeError("prepared must be a PreparedAccountCommit")
        if prepared is not self._prepared:
            raise ValueError(
                "prepared commit was not produced by this Account or is no longer current"
            )
        if prepared.expected_version != self._snapshot.version:
            raise ValueError("prepared commit is stale")

        # All objects have been constructed and validated before publication.
        published = AccountSnapshot(
            prepared.next_snapshot.version,
            prepared.next_snapshot.cash,
            prepared.next_snapshot.positions,
        )
        self._snapshot = published
        self._journal.extend(prepared.journal_entries)
        self._history.append(self.snapshot())
        self._prepared = None
        return self.snapshot()
