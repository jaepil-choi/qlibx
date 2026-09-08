"""Timestamp-free Strategy-to-execution economic intent contract."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from vqapr.domain.identifiers import ModelStateRef
from vqapr.portfolio.budgets import Budget


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


__all__ = [
    "EconomicPortfolioIntent",
    "IntentSourceRef",
    "PortfolioTarget",
    "validate_economic_intent",
]
