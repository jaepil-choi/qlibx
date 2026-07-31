"""Book backtester interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from echolon.panel import PanelData
from echolon.portfolio import PortfolioStrategy

from .models import BookBacktestConfig, BookResult


class IBookBacktester(ABC):
    """Run a portfolio strategy over a panel snapshot."""

    @abstractmethod
    def run(
        self,
        strategy: PortfolioStrategy,
        panel: PanelData,
        config: BookBacktestConfig,
    ) -> BookResult:
        """Run the backtest and return in-memory artifacts."""

