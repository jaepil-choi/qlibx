"""Atomic actual-state account aggregate."""

import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from qlibx.domain import Fill, Side


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("account change as_of must be timezone-aware")


class ValuationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class Position:
    instrument_id: str
    quantity: float
    average_cost: float
    realized_pnl: float = 0
    mark: float | None = None
    marked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FillBatch:
    account_id: str
    event_id: str
    as_of: datetime
    fills: tuple[Fill, ...]

    def __post_init__(self) -> None:
        _require_aware(self.as_of)


@dataclass(frozen=True, slots=True)
class Mark:
    instrument_id: str
    price: float


@dataclass(frozen=True, slots=True)
class MarkBatch:
    account_id: str
    event_id: str
    as_of: datetime
    marks: tuple[Mark, ...]

    def __post_init__(self) -> None:
        _require_aware(self.as_of)


AccountChange = FillBatch | MarkBatch


@dataclass(frozen=True, slots=True)
class JournalEntry:
    cursor: int
    event_id: str
    as_of: datetime
    change_type: str
    fill_ids: tuple[str, ...] = ()
    fills: tuple[Fill, ...] = ()
    marks: tuple[Mark, ...] = ()
    realized_pnl: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: str
    base_currency: str
    version: int
    cash: float
    positions: tuple[Position, ...]
    nav: float
    valuation_status: ValuationStatus
    feedback_cursor: int
    as_of: datetime | None
    realized_pnl: tuple[tuple[str, float], ...] = ()

    def holdings(self) -> dict[str, float]:
        return {position.instrument_id: position.quantity for position in self.positions}


@dataclass(frozen=True, slots=True)
class AccountFeedback:
    account_id: str
    after_cursor: int
    entries: tuple[JournalEntry, ...]
    next_cursor: int


@dataclass(frozen=True, slots=True)
class AccountCommit:
    event_id: str
    previous_version: int
    version: int
    feedback_cursor: int
    snapshot: AccountSnapshot


@dataclass(frozen=True, slots=True)
class AccountCheckpoint:
    account_id: str
    base_currency: str
    cash: float
    instrument_ids: tuple[str, ...]
    positions: tuple[Position, ...]
    version: int
    applied_events: tuple[str, ...]
    journal: tuple[JournalEntry, ...]
    as_of: datetime | None
    realized_pnl: tuple[tuple[str, float], ...] = ()


class AccountCommitRejected(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Account:
    """Own cash, positions, marks, journal, idempotency, and version."""

    def __init__(
        self,
        *,
        account_id: str,
        base_currency: str,
        initial_cash: float,
        instrument_ids: frozenset[str],
    ) -> None:
        if not account_id or initial_cash < 0:
            raise ValueError("account requires an identity and non-negative initial cash")
        self._account_id = account_id
        self._base_currency = base_currency
        self._cash = initial_cash
        self._instrument_ids = instrument_ids
        self._positions: dict[str, Position] = {}
        self._realized_pnl: dict[str, float] = {}
        self._version = 0
        self._applied_events: set[str] = set()
        self._journal: list[JournalEntry] = []
        self._as_of: datetime | None = None

    def snapshot(self, *, evaluation_time: datetime | None = None) -> AccountSnapshot:
        if evaluation_time is not None:
            _require_aware(evaluation_time)
            if self._as_of is not None and self._as_of > evaluation_time:
                raise ValueError("account state is later than the requested evaluation time")
        positions = tuple(sorted(self._positions.values(), key=lambda item: item.instrument_id))
        incomplete = any(
            position.mark is None or position.marked_at is None for position in positions
        )
        stale = (
            evaluation_time is not None
            and not incomplete
            and any(position.marked_at < evaluation_time for position in positions)
        )
        marked_value = sum(
            position.quantity * position.mark
            for position in positions
            if position.mark is not None
        )
        return AccountSnapshot(
            account_id=self._account_id,
            base_currency=self._base_currency,
            version=self._version,
            cash=self._cash,
            positions=positions,
            nav=self._cash + marked_value,
            valuation_status=(
                ValuationStatus.INCOMPLETE
                if incomplete
                else ValuationStatus.STALE
                if stale
                else ValuationStatus.COMPLETE
            ),
            feedback_cursor=len(self._journal),
            as_of=self._as_of,
            realized_pnl=tuple(sorted(self._realized_pnl.items())),
        )

    def checkpoint(self) -> AccountCheckpoint:
        return AccountCheckpoint(
            account_id=self._account_id,
            base_currency=self._base_currency,
            cash=self._cash,
            instrument_ids=tuple(sorted(self._instrument_ids)),
            positions=tuple(
                sorted(self._positions.values(), key=lambda item: item.instrument_id)
            ),
            version=self._version,
            applied_events=tuple(sorted(self._applied_events)),
            journal=tuple(self._journal),
            as_of=self._as_of,
            realized_pnl=tuple(sorted(self._realized_pnl.items())),
        )

    @classmethod
    def from_checkpoint(cls, checkpoint: AccountCheckpoint) -> "Account":
        if checkpoint.version != len(checkpoint.journal):
            raise ValueError("account checkpoint version and journal length differ")
        if set(checkpoint.applied_events) != {
            entry.event_id for entry in checkpoint.journal
        }:
            raise ValueError("account checkpoint event identities do not match its journal")
        if checkpoint.journal:
            if tuple(entry.as_of for entry in checkpoint.journal) != tuple(
                sorted(entry.as_of for entry in checkpoint.journal)
            ):
                raise ValueError("account checkpoint events are not time ordered")
            if checkpoint.as_of != checkpoint.journal[-1].as_of:
                raise ValueError("account checkpoint as_of does not match its journal")
        elif checkpoint.as_of is not None:
            raise ValueError("empty account checkpoint cannot have an as_of")
        current = cls(
            account_id=checkpoint.account_id,
            base_currency=checkpoint.base_currency,
            initial_cash=checkpoint.cash,
            instrument_ids=frozenset(checkpoint.instrument_ids),
        )
        if any(
            position.instrument_id not in current._instrument_ids
            for position in checkpoint.positions
        ):
            raise ValueError("account checkpoint contains an unregistered position")
        current._positions = {
            position.instrument_id: position for position in checkpoint.positions
        }
        if any(
            instrument_id not in current._instrument_ids
            for instrument_id, _ in checkpoint.realized_pnl
        ):
            raise ValueError("account checkpoint contains unregistered realized PnL")
        if len({instrument_id for instrument_id, _ in checkpoint.realized_pnl}) != len(
            checkpoint.realized_pnl
        ):
            raise ValueError("account checkpoint contains duplicate realized PnL")
        checkpoint_realized = dict(checkpoint.realized_pnl)
        if not checkpoint_realized:
            checkpoint_realized = {
                position.instrument_id: position.realized_pnl
                for position in checkpoint.positions
                if position.realized_pnl != 0
            }
        if any(not math.isfinite(value) for value in checkpoint_realized.values()):
            raise ValueError("account checkpoint contains non-finite realized PnL")
        if any(
            not math.isclose(
                position.realized_pnl,
                checkpoint_realized.get(position.instrument_id, 0),
                rel_tol=0,
                abs_tol=1e-9,
            )
            for position in checkpoint.positions
        ):
            raise ValueError("account checkpoint position and realized PnL differ")
        current._realized_pnl = checkpoint_realized
        current._version = checkpoint.version
        current._applied_events = set(checkpoint.applied_events)
        current._journal = list(checkpoint.journal)
        current._as_of = checkpoint.as_of
        return current

    def feedback(self, after: int, limit: int) -> AccountFeedback:
        if after < 0 or limit < 0 or after > len(self._journal):
            raise ValueError("invalid feedback cursor or limit")
        entries = tuple(self._journal[after : after + limit])
        return AccountFeedback(
            account_id=self._account_id,
            after_cursor=after,
            entries=entries,
            next_cursor=after + len(entries),
        )

    def commit(self, change: AccountChange, *, expected_version: int) -> AccountCommit:
        if change.account_id != self._account_id:
            raise AccountCommitRejected("ACCOUNT_ID_MISMATCH", "change targets another account")
        if change.event_id in self._applied_events:
            raise AccountCommitRejected("DUPLICATE_EVENT", "event was already applied")
        if expected_version != self._version:
            raise AccountCommitRejected("STALE_VERSION", "expected_version does not match account")
        if self._as_of is not None and change.as_of < self._as_of:
            raise AccountCommitRejected(
                "OUT_OF_ORDER_EVENT",
                "change precedes current account state",
            )

        cash = self._cash
        positions = dict(self._positions)
        realized_pnl = dict(self._realized_pnl)
        if isinstance(change, FillBatch):
            cash, positions, realized_pnl, realized_delta = self._apply_fills(
                change.fills,
                cash,
                positions,
                realized_pnl,
            )
            fill_ids = tuple(fill.fill_id for fill in change.fills)
            fills = change.fills
            marks = ()
        else:
            positions = self._apply_marks(change.marks, positions, change.as_of)
            fill_ids = ()
            fills = ()
            marks = change.marks
            realized_delta = ()
        if cash < -1e-9:
            raise AccountCommitRejected("NEGATIVE_CASH", "batch would leave negative cash")

        previous = self._version
        self._cash = cash
        self._positions = positions
        self._realized_pnl = realized_pnl
        self._applied_events.add(change.event_id)
        self._as_of = change.as_of
        self._version += 1
        self._journal.append(
            JournalEntry(
                cursor=len(self._journal) + 1,
                event_id=change.event_id,
                as_of=change.as_of,
                change_type=type(change).__name__,
                fill_ids=fill_ids,
                fills=fills,
                marks=marks,
                realized_pnl=realized_delta,
            )
        )
        snapshot = self.snapshot(evaluation_time=change.as_of)
        return AccountCommit(
            event_id=change.event_id,
            previous_version=previous,
            version=self._version,
            feedback_cursor=len(self._journal),
            snapshot=snapshot,
        )

    def _apply_fills(
        self,
        fills: tuple[Fill, ...],
        cash: float,
        positions: dict[str, Position],
        realized_pnl: dict[str, float],
    ) -> tuple[
        float,
        dict[str, Position],
        dict[str, float],
        tuple[tuple[str, float], ...],
    ]:
        seen: set[str] = set()
        realized_delta: dict[str, float] = {}
        for fill in fills:
            if fill.fill_id in seen:
                raise AccountCommitRejected("DUPLICATE_FILL", "batch contains duplicate fill IDs")
            seen.add(fill.fill_id)
            if fill.instrument_id not in self._instrument_ids:
                raise AccountCommitRejected(
                    "INSTRUMENT_NOT_REGISTERED",
                    f"instrument {fill.instrument_id} is not registered",
                )
            current = positions.get(fill.instrument_id)
            if fill.side is Side.BUY:
                old_quantity = current.quantity if current else 0
                old_basis = old_quantity * current.average_cost if current else 0
                new_quantity = old_quantity + fill.dealt_quantity
                new_basis = old_basis + fill.trade_value + fill.total_cost
                positions[fill.instrument_id] = Position(
                    instrument_id=fill.instrument_id,
                    quantity=new_quantity,
                    average_cost=new_basis / new_quantity if new_quantity else 0,
                    realized_pnl=realized_pnl.get(fill.instrument_id, 0),
                    mark=current.mark if current else None,
                    marked_at=current.marked_at if current else None,
                )
                cash -= fill.trade_value + fill.total_cost
            else:
                if current is None or fill.dealt_quantity > current.quantity:
                    raise AccountCommitRejected(
                        "SELL_EXCEEDS_POSITION",
                        "sell exceeds actual position",
                    )
                quantity = current.quantity - fill.dealt_quantity
                if 0 < quantity <= 1e-12:
                    raise AccountCommitRejected(
                        "POSITION_DUST_UNSUPPORTED",
                        "sell would silently discard a positive residual position",
                    )
                delta = (
                    (fill.price - current.average_cost) * fill.dealt_quantity
                    - fill.total_cost
                )
                realized = realized_pnl.get(fill.instrument_id, 0) + delta
                realized_pnl[fill.instrument_id] = realized
                realized_delta[fill.instrument_id] = (
                    realized_delta.get(fill.instrument_id, 0) + delta
                )
                if quantity == 0:
                    positions.pop(fill.instrument_id)
                else:
                    positions[fill.instrument_id] = replace(
                        current,
                        quantity=quantity,
                        realized_pnl=realized,
                    )
                cash += fill.trade_value - fill.total_cost
        return cash, positions, realized_pnl, tuple(sorted(realized_delta.items()))

    def _apply_marks(
        self,
        marks: tuple[Mark, ...],
        positions: dict[str, Position],
        as_of: datetime,
    ) -> dict[str, Position]:
        seen: set[str] = set()
        for mark in marks:
            if mark.instrument_id in seen:
                raise AccountCommitRejected("DUPLICATE_MARK", "batch contains duplicate marks")
            seen.add(mark.instrument_id)
            if mark.instrument_id not in self._instrument_ids:
                raise AccountCommitRejected("INSTRUMENT_NOT_REGISTERED", "mark is not registered")
            if mark.price <= 0:
                raise AccountCommitRejected("INVALID_MARK", "mark price must be positive")
            current = positions.get(mark.instrument_id)
            if current is not None:
                positions[mark.instrument_id] = replace(
                    current,
                    mark=mark.price,
                    marked_at=as_of,
                )
        return positions
