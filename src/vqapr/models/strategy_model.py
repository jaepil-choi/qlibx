"""Stateful Strategy session-callback contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from vqapr.models.memory import ModelMemory
from vqapr.portfolio.intents import PortfolioIntent
from vqapr.runtime.events import LocalEvaluationTime, SessionEvent


@dataclass(frozen=True, slots=True)
class NoDecision:
    """A successful callback that intentionally emits no PortfolioIntent."""

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("NoDecision reason must be non-empty")


@dataclass(frozen=True, slots=True)
class StrategyModelContext:
    """The current session only; there is deliberately no future-session surface."""

    session: SessionEvent

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionEvent):
            raise TypeError("session must be a SessionEvent")


class StrategyModel(ABC):
    """User extension whose memory owns cadence and other path-dependent rules."""

    memory: ModelMemory = None

    @abstractmethod
    def callback_time(self) -> LocalEvaluationTime:
        """Return the evaluation wall time used for every current execution session."""

    @abstractmethod
    def on_session(self, context: StrategyModelContext) -> NoDecision | PortfolioIntent:
        """Return NoDecision or a PortfolioIntent-compatible value."""
