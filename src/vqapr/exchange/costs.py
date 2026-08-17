"""Venue-owned execution cost rules.

A profile declares its costs as an ordered tuple of :class:`CostRule`. Exactly one rule must match
a given side; zero matches and several matches are both failures. Nothing here guesses a default
rate, and no rule silently applies to a side it did not declare.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from vqapr.domain.enums import Side


def _rate(value: Decimal, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite non-negative rate")
    return value


@dataclass(frozen=True, slots=True)
class FillCost:
    """The charged components for one dealt fill, kept separate for reporting."""

    commission: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _rate(self.commission, name="commission")
        _rate(self.tax, name="tax")

    @property
    def total(self) -> Decimal:
        return self.commission + self.tax

    def __bool__(self) -> bool:
        return bool(self.total)


@dataclass(frozen=True, slots=True)
class CostRule:
    """One declared cost band for one side of a venue."""

    rule_id: str
    side: Side
    commission_rate: Decimal
    tax_rate: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError("rule_id must be a non-empty string")
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side")
        _rate(self.commission_rate, name="commission_rate")
        _rate(self.tax_rate, name="tax_rate")

    def charge(self, notional: Decimal) -> FillCost:
        """Charge this rule against a positive traded notional."""
        if not isinstance(notional, Decimal):
            raise TypeError("notional must be a Decimal")
        if not notional.is_finite() or notional < 0:
            raise ValueError("notional must be a finite non-negative Decimal")
        return FillCost(
            commission=notional * self.commission_rate,
            tax=notional * self.tax_rate,
        )

    @property
    def declaration_identity(self) -> tuple[str, str, str, str]:
        return (self.rule_id, self.side.value, str(self.commission_rate), str(self.tax_rate))


def select_cost_rule(rules: Sequence[CostRule], side: Side) -> CostRule:
    """Return the single rule declared for ``side`` or fail with the observed match count."""
    if not isinstance(side, Side):
        raise TypeError("side must be a Side")
    matched = [rule for rule in rules if rule.side is side]
    if len(matched) != 1:
        raise ValueError(
            f"exactly one CostRule must match side {side.value!r}; matched {len(matched)}"
        )
    return matched[0]


def charge_fill(rules: Sequence[CostRule], side: Side, notional: Decimal) -> FillCost:
    """Resolve the one matching rule and charge it."""
    return select_cost_rule(rules, side).charge(notional)
