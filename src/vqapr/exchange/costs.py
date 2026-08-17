"""Venue-owned execution cost rules.

A profile declares its costs as an ordered tuple of :class:`CostRule`. Exactly one rule must match
a given side; zero matches and several matches are both failures. Nothing here guesses a default
rate, and no rule silently applies to a side it did not declare.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from vqapr.domain.enums import Side
from vqapr.domain.timestamps import require_tz_aware


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
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError("rule_id must be a non-empty string")
        if not isinstance(self.side, Side):
            raise TypeError("side must be a Side")
        _rate(self.commission_rate, name="commission_rate")
        _rate(self.tax_rate, name="tax_rate")
        for name, value in (
            ("effective_from", self.effective_from),
            ("effective_to", self.effective_to),
        ):
            if value is not None:
                require_tz_aware(value, name=name)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_from >= self.effective_to
        ):
            raise ValueError("effective_from must precede effective_to")

    @property
    def always_effective(self) -> bool:
        return self.effective_from is None and self.effective_to is None

    def effective_at(self, at: datetime | None) -> bool:
        """Half-open ``[effective_from, effective_to)`` membership.

        A rule with no declared window is always effective. A dated rule can only be selected
        against an actual instant, so an undated query never matches it.
        """
        if self.always_effective:
            return True
        if at is None:
            return False
        require_tz_aware(at, name="at")
        if self.effective_from is not None and at < self.effective_from:
            return False
        return not (self.effective_to is not None and at >= self.effective_to)

    def matches(self, side: Side, at: datetime | None = None) -> bool:
        return self.side is side and self.effective_at(at)

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
    def declaration_identity(self) -> tuple[str, ...]:
        return (
            self.rule_id,
            self.side.value,
            str(self.commission_rate),
            str(self.tax_rate),
            "" if self.effective_from is None else self.effective_from.isoformat(),
            "" if self.effective_to is None else self.effective_to.isoformat(),
        )


def select_cost_rule(rules: Sequence[CostRule], side: Side, at: datetime | None = None) -> CostRule:
    """Return the single rule effective for ``side`` at ``at`` or fail with the match count."""
    if not isinstance(side, Side):
        raise TypeError("side must be a Side")
    matched = [rule for rule in rules if rule.matches(side, at)]
    if len(matched) != 1:
        moment = "any instant" if at is None else at.isoformat()
        raise ValueError(
            f"exactly one CostRule must match side {side.value!r} at {moment}; "
            f"matched {len(matched)}"
        )
    return matched[0]


def effective_rules(rules: Sequence[CostRule], at: datetime | None) -> tuple[CostRule, ...]:
    """Narrow a declaration to the rules effective at one instant."""
    return tuple(rule for rule in rules if rule.effective_at(at))


def charge_fill(
    rules: Sequence[CostRule], side: Side, notional: Decimal, at: datetime | None = None
) -> FillCost:
    """Resolve the one effective rule and charge it."""
    return select_cost_rule(rules, side, at).charge(notional)
