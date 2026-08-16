"""Detached immutable account state exposed to execution planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType


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
