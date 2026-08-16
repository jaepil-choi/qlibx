"""Timestamp-free Strategy-to-execution economic intent contract."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from vqapr.domain.references import ModelStateRef


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    """One complete desired position expressed in exactly one economic unit."""

    instrument_id: str
    weight: Decimal | None = None
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if (self.weight is None) == (self.quantity is None):
            raise ValueError("exactly one of weight or quantity must be set")
        value = self.weight if self.weight is not None else self.quantity
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("target value must be a finite Decimal")


@runtime_checkable
class EconomicPortfolioIntent(Protocol):
    """Timestamp-free economic payload accepted only by the Flow boundary."""

    intent_id: UUID
    strategy_id: str
    targets: tuple[PortfolioTarget, ...]
    cash_target: Decimal
    budget: object
    source_refs: tuple[object, ...]
    account_version_seen: int
    model_state_ref: ModelStateRef | None


def validate_economic_intent(intent: object) -> EconomicPortfolioIntent:
    """Reject timing authority and incomplete economic target declarations."""
    if not isinstance(intent, EconomicPortfolioIntent):
        raise TypeError("intent must satisfy EconomicPortfolioIntent")
    for field in ("decision_time", "effective_after"):
        if hasattr(intent, field):
            raise ValueError(f"economic intent must not declare {field}")
    if not isinstance(intent.intent_id, UUID):
        raise TypeError("intent_id must be a UUID")
    if not isinstance(intent.strategy_id, str) or not intent.strategy_id.strip():
        raise ValueError("strategy_id must be a non-empty string")
    if not isinstance(intent.targets, tuple):
        raise TypeError("targets must be a tuple")
    if not all(isinstance(target, PortfolioTarget) for target in intent.targets):
        raise TypeError("targets must contain PortfolioTarget values")
    if len({target.instrument_id for target in intent.targets}) != len(intent.targets):
        raise ValueError("targets must contain each instrument at most once")
    if not isinstance(intent.cash_target, Decimal) or not intent.cash_target.is_finite():
        raise TypeError("cash_target must be a finite Decimal")
    if not isinstance(intent.source_refs, tuple):
        raise TypeError("source_refs must be a tuple")
    if isinstance(intent.account_version_seen, bool) or not isinstance(
        intent.account_version_seen, int
    ):
        raise TypeError("account_version_seen must be an integer")
    return intent
