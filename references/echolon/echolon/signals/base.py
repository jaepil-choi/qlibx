"""Signal engine abstract base class."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from echolon.panel import PanelData, PanelView

from .models import ScoreVector


class SignalEngine(ABC):
    """Compute standardized instrument scores from a panel view.

    Scores are unitless and capped to +/-3.0 by the S2 contract. Implementations
    return ``None`` for instruments whose data requirements are unmet.
    """

    signal_id: str
    family: str
    params: Mapping[str, float | int]
    data_requirements: Mapping[str, Any]

    @abstractmethod
    def compute(self, view: PanelView) -> ScoreVector:
        """Return scores known as of ``view.date``."""

    def compute_history(self, panel: PanelData, dates: Sequence[dt.date]) -> list[ScoreVector]:
        """Compute history by looping over ``panel.view(date)`` for each date."""
        return [self.compute(panel.view(date)) for date in dates]

