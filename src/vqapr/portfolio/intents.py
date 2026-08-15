"""Nominal Strategy-to-execution intent surface used by the callback boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from vqapr.domain.references import ModelStateRef


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
