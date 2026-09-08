"""Detached immutable account state exposed to execution planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, field_validator

from vqapr.domain.values import MarkBatch, require_tz_aware


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
    provenance: object
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
    """Immutable Account authority embedded exclusively in an accepted run root."""

    snapshot: AccountSnapshot
    mark_history: tuple[AccountMark, ...] = ()
    fill_history: tuple[object, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AccountSnapshot):
            raise TypeError("snapshot must be an AccountSnapshot")
        if not isinstance(self.mark_history, tuple) or any(
            not isinstance(mark, AccountMark) for mark in self.mark_history
        ):
            raise TypeError("mark_history must be a tuple of AccountMark")
        if not isinstance(self.fill_history, tuple):
            raise TypeError("fill_history must be a tuple")
        if self.mark_history:
            versions = tuple(mark.account_version for mark in self.mark_history)
            # Non-decreasing, not strictly increasing: an occurrence that trades nothing marks
            # the book without advancing the account version, so one version can carry several
            # marks. What must never happen is a mark for an earlier version arriving later.
            if any(later < earlier for earlier, later in pairwise(versions)):
                raise ValueError("mark history versions must not decrease")
            instants = tuple(
                mark.marked_at for mark in self.mark_history if mark.marked_at is not None
            )
            if any(later <= earlier for earlier, later in pairwise(instants)):
                raise ValueError("mark history instants must be strictly increasing")
            latest = self.mark_history[-1]
            if latest.account_version > self.snapshot.version:
                raise ValueError("latest mark cannot belong to a future Account snapshot")
            if (
                latest.account_version == self.snapshot.version
                and latest.nav != self.snapshot.cash + latest.marks.total_value
            ):
                raise ValueError("latest mark NAV must match the current Account snapshot")

    @property
    def latest_mark(self) -> AccountMark | None:
        return self.mark_history[-1] if self.mark_history else None
