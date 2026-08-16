"""Detached immutable account state exposed to execution planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from vqapr.valuation.marks import MarkBatch


def _decimal(value: object, *, name: str, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """A value snapshot that cannot expose or alias mutable Account state."""

    version: int
    cash: Decimal
    positions: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        _decimal(self.cash, name="cash", nonnegative=True)
        if not isinstance(self.positions, Mapping):
            raise TypeError("positions must be a mapping")
        normalized: dict[str, Decimal] = {}
        for instrument_id, quantity in self.positions.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise ValueError("position instrument ids must be non-empty strings")
            value = _decimal(quantity, name=f"positions[{instrument_id!r}]")
            if value != 0:
                normalized[instrument_id] = value
        object.__setattr__(self, "positions", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class AccountMark:
    """The complete valuation published for one Account snapshot."""

    account_version: int
    marks: MarkBatch
    nav: Decimal
    provenance: object

    def __post_init__(self) -> None:
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(self.marks, MarkBatch):
            raise TypeError("marks must be a MarkBatch")
        _decimal(self.nav, name="nav")


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
            if versions != tuple(sorted(set(versions))):
                raise ValueError("mark history versions must be strictly increasing")
            latest = self.mark_history[-1]
            if latest.account_version != self.snapshot.version:
                raise ValueError("latest mark must belong to the current account version")
            if latest.nav != self.snapshot.cash + latest.marks.total_value:
                raise ValueError("latest mark NAV must match the current Account snapshot")

    @property
    def latest_mark(self) -> AccountMark | None:
        return self.mark_history[-1] if self.mark_history else None
