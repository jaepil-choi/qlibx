"""Walk-Forward Analysis window definitions."""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List

import pandas as pd


@dataclass
class WFAWindow:
    """A single walk-forward analysis window."""

    window_id: int
    is_start: str       # e.g. "2018-01-01"
    is_end: str         # e.g. "2020-12-31"
    oos_start: str      # e.g. "2021-01-01"
    oos_end: str        # e.g. "2021-12-31"

    # Populated after optimization
    is_sharpe: Optional[float] = None
    oos_sharpe: Optional[float] = None
    oos_results: Optional[Dict[str, Any]] = None
    selected_trial: Optional[Dict[str, Any]] = None

    @property
    def walk_forward_efficiency(self) -> Optional[float]:
        """WFE = OOS_sharpe / IS_sharpe. None if IS_sharpe is 0 or unavailable."""
        if self.is_sharpe and self.is_sharpe != 0 and self.oos_sharpe is not None:
            return self.oos_sharpe / self.is_sharpe
        return None

    @property
    def is_years(self) -> float:
        return (pd.Timestamp(self.is_end) - pd.Timestamp(self.is_start)).days / 365.25

    @property
    def oos_years(self) -> float:
        return (pd.Timestamp(self.oos_end) - pd.Timestamp(self.oos_start)).days / 365.25


@dataclass
class WFAConfig:
    """Configuration for the WFA run."""

    windows: List[WFAWindow]
    trials_per_window: int = 200
    optimization_target: str = "multi_objective"
    max_drawdown_threshold: float = 15.0
