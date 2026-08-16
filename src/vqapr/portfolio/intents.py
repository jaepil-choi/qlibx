"""Nominal Strategy-to-execution intent surface used by the callback boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from vqapr.domain.references import ModelStateRef


@runtime_checkable
class EconomicPortfolioIntent(Protocol):
    """Timestamp-free economic payload accepted only by the future Flow boundary."""

    intent_id: UUID
    strategy_id: str
    targets: tuple[object, ...]
    cash_target: Decimal
    budget: object
    source_refs: tuple[object, ...]
    account_version_seen: int
    model_state_ref: ModelStateRef | None


def validate_economic_intent(intent: object) -> EconomicPortfolioIntent:
    """Reject timing authority before Flow stamps its own decision instant."""

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
    if not isinstance(intent.cash_target, Decimal):
        raise TypeError("cash_target must be a Decimal")
    if not isinstance(intent.source_refs, tuple):
        raise TypeError("source_refs must be a tuple")
    if isinstance(intent.account_version_seen, bool) or not isinstance(
        intent.account_version_seen,
        int,
    ):
        raise TypeError("account_version_seen must be an integer")
    return intent


@runtime_checkable
class PortfolioIntent(Protocol):
    """Validated intent shape; concrete construction and economics are a later portfolio slice."""

    intent_id: UUID
    strategy_id: str
    decision_time: datetime
    effective_after: datetime
    targets: tuple[object, ...]
    cash_target: Decimal
    budget: object
    source_refs: tuple[object, ...]
    account_version_seen: int
    model_state_ref: ModelStateRef | None
