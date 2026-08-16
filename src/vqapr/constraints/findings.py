"""Immutable evidence emitted by Constraint evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType


def _decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class ConstraintFinding:
    """One Constraint's complete result for one immutable account observation."""

    constraint_id: str
    passed: bool
    measured: Decimal
    bound: Decimal
    excess: Decimal
    input_lineage: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.constraint_id, str) or not self.constraint_id:
            raise ValueError("constraint_id must be a non-empty string")
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a bool")
        _decimal(self.measured, name="measured")
        _decimal(self.bound, name="bound")
        _decimal(self.excess, name="excess")
        if not isinstance(self.input_lineage, Mapping):
            raise TypeError("input_lineage must be a mapping")
        object.__setattr__(self, "input_lineage", MappingProxyType(dict(self.input_lineage)))


@dataclass(frozen=True, slots=True)
class ConstraintReport:
    """All findings from one closed evaluation of a committed account version."""

    account_version: int
    findings: tuple[ConstraintFinding, ...]

    def __post_init__(self) -> None:
        if isinstance(self.account_version, bool) or not isinstance(self.account_version, int):
            raise TypeError("account_version must be an integer")
        if self.account_version < 0:
            raise ValueError("account_version must be non-negative")
        if not isinstance(self.findings, tuple) or not all(
            isinstance(finding, ConstraintFinding) for finding in self.findings
        ):
            raise TypeError("findings must be a tuple of ConstraintFinding")
        ids = tuple(finding.constraint_id for finding in self.findings)
        if len(ids) != len(set(ids)):
            raise ValueError("findings must contain each constraint_id once")

    @property
    def passed(self) -> bool:
        return all(finding.passed for finding in self.findings)
