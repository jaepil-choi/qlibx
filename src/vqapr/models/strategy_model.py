"""Stateful Strategy occurrence-callback contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO

from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.models.contexts import StrategyModelContext
from vqapr.models.memory import ModelMemory
from vqapr.models.model import Model
from vqapr.portfolio.intents import EconomicPortfolioIntent


@dataclass(frozen=True, slots=True)
class NoDecision:
    """A successful callback that intentionally emits no economic intent."""

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("NoDecision reason must be non-empty")


class StrategyModel(Model, ABC):
    """User extension whose memory owns cadence and other path-dependent rules."""

    memory: ModelMemory = None
    recorder: InvocationRecorder | None = None

    def tables(self) -> tuple[TableSpec, ...]:
        """Declare diagnostic tables available during one callback invocation."""
        return ()

    def save_payload(self, target: BinaryIO) -> None:
        """Persist private callback state into Flow-owned staging."""

    def load_payload(self, source: BinaryIO) -> None:
        """Restore private callback state from Flow-owned staging."""

    @abstractmethod
    def on_occurrence(self, context: StrategyModelContext) -> NoDecision | EconomicPortfolioIntent:
        """Return NoDecision or a timestamp-free economic intent."""
