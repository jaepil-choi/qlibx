"""The target portfolio a strategy's decision becomes.

An intent is target weights, a cash target and the `Budget` they must satisfy -- the direction
(long-only or signed), the cash range and the per-position range. The budget travels with the intent
and is checked again where the intent is accepted and where it is planned into orders. A target is a
weight, never a quantity: the strategy sees no fill price and no NAV. Timing is the engine's to
stamp, so nothing here carries a decision time.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from vqapr.domain.identifiers import ModelStateRef

__all__ = [
    "Budget",
    "EconomicPortfolioIntent",
    "IntentSourceRef",
    "PortfolioDirection",
    "PortfolioTarget",
    "validate_economic_intent",
]


class PortfolioDirection(StrEnum):
    """The signedness permitted for a complete intended portfolio."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


class Budget(BaseModel):
    """Declared cash and per-position bounds for one economic intent.

    The declaration is a value, not a strategy-owned mutable configuration.  It
    therefore travels with the intent and is independently checked at the Flow
    boundary.

    **The two budgets the authoring constructors make, as numbers** -- named here because an
    author building a `Rebalance` directly had to reconstruct them from a sentence inside
    `Rebalance.of`'s docstring (`docs/issues/archive/075`):

    ```python
    Budget(direction=PortfolioDirection.LONG_ONLY,   # Rebalance.of with no `short=`
           cash_lower=Decimal(0),  cash_upper=Decimal(1),
           target_lower=Decimal(0), target_upper=Decimal(1))

    Budget(direction=PortfolioDirection.SIGNED,      # Rebalance.of with `short=`, and .signed
           cash_lower=Decimal(-1), cash_upper=Decimal(2),
           target_lower=Decimal(-1), target_upper=Decimal(1))
    ```

    `cash_upper` is 2 on a signed book and not 1 because **selling short raises cash**: a book
    that is only short holds more than its NAV in cash, by exactly what it shorted. Pinning it at
    1 refused every short-only book, naming cash when the bound was what was wrong.

    Strict: every bound is a finite `Decimal` and the direction an enum member, refused rather
    than coerced -- an author's `cash_upper=1` is a different value from `Decimal(1)` downstream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    direction: PortfolioDirection
    cash_lower: Decimal
    cash_upper: Decimal
    target_lower: Decimal
    target_upper: Decimal

    def __init__(
        self,
        direction: PortfolioDirection,
        cash_lower: Decimal,
        cash_upper: Decimal,
        target_lower: Decimal,
        target_upper: Decimal,
    ) -> None:
        # Positional as well as keyword: the shipped sample strategy and the tests spell the
        # five bounds in declaration order.
        super().__init__(
            direction=direction,
            cash_lower=cash_lower,
            cash_upper=cash_upper,
            target_lower=target_lower,
            target_upper=target_upper,
        )

    @model_validator(mode="after")
    def _ordered_and_signed(self) -> Self:
        if self.cash_lower > self.cash_upper:
            raise ValueError("cash_lower must not exceed cash_upper")
        if self.target_lower > self.target_upper:
            raise ValueError("target_lower must not exceed target_upper")
        if self.direction is PortfolioDirection.LONG_ONLY and (
            self.cash_lower < 0 or self.target_lower < 0
        ):
            raise ValueError("long_only budgets cannot permit negative cash or targets")
        return self

    def validates_cash(self, value: Decimal) -> bool:
        """Return whether an already-validated cash target is within this budget."""
        return self.cash_lower <= value <= self.cash_upper

    def validates_target(self, value: Decimal) -> bool:
        """Return whether an already-validated target is within this budget."""
        return self.target_lower <= value <= self.target_upper


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    """One complete desired position, expressed as a fraction of execution-time NAV.

    A target is a weight and never a quantity. The callback cannot see the execution price or
    NAV, so a quantity it named would have to be derived from an earlier price; ``plan_orders``
    exists precisely to do that conversion later, at the price the fill actually uses.
    """

    instrument_id: str
    weight: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if not isinstance(self.weight, Decimal) or not self.weight.is_finite():
            raise ValueError("weight must be a finite Decimal")


@dataclass(frozen=True, slots=True)
class IntentSourceRef:
    """Stable identity of one source artifact consumed by a Strategy."""

    source_id: str
    content_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_id, str)
            or not self.source_id
            or any(character.isspace() for character in self.source_id)
        ):
            raise ValueError("source_id must be a non-empty identifier without whitespace")
        if (
            not isinstance(self.content_digest, str)
            or len(self.content_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.content_digest)
        ):
            raise ValueError("content_digest must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class EconomicPortfolioIntent:
    """Timestamp-free, complete economic payload accepted by the Flow."""

    intent_id: UUID
    strategy_id: str
    targets: tuple[PortfolioTarget, ...]
    cash_target: Decimal
    budget: Budget
    source_refs: tuple[IntentSourceRef, ...]
    account_version_seen: int
    model_state_ref: ModelStateRef | None


def validate_economic_intent(intent: EconomicPortfolioIntent) -> EconomicPortfolioIntent:
    """Reject timing authority and incomplete economic target declarations."""
    for field in ("decision_time", "effective_after"):
        if hasattr(intent, field):
            raise ValueError(f"economic intent must not declare {field}")
    if not intent.strategy_id or any(character.isspace() for character in intent.strategy_id):
        raise ValueError("strategy_id must be a non-empty identifier without whitespace")
    if len({target.instrument_id for target in intent.targets}) != len(intent.targets):
        raise ValueError("targets must contain each instrument at most once")
    if not intent.cash_target.is_finite():
        raise ValueError("cash_target must be a finite Decimal")
    if not intent.budget.validates_cash(intent.cash_target):
        raise ValueError("cash_target is outside the declared budget")
    if intent.targets:
        target_values = tuple(target.weight for target in intent.targets)
        if any(not intent.budget.validates_target(value) for value in target_values):
            raise ValueError("target is outside the declared budget bounds")
        if sum(target_values, Decimal("0")) + intent.cash_target != 1:
            raise ValueError("weight targets plus cash_target must equal one")
    elif intent.cash_target != 1:
        raise ValueError("an empty complete position set requires cash_target equal to one")
    if len({source.source_id for source in intent.source_refs}) != len(intent.source_refs):
        raise ValueError("source_refs must not contain duplicate provenance")
    if isinstance(intent.account_version_seen, bool) or not isinstance(
        intent.account_version_seen, int
    ):
        raise TypeError("account_version_seen must be an integer")
    if intent.account_version_seen < 0:
        raise ValueError("account_version_seen must be non-negative")
    return intent
