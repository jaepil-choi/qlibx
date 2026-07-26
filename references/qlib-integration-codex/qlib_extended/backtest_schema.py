from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ExecutionConfig:
    volume: str | None = None
    max_volume_participation: float | None = None


@dataclass(frozen=True)
class MatchedCapitalizationConfig:
    observed: str
    tradable: str
    shortable: str
    per_name_short_cap: float
    safety_multiplier: float = 1.0
    inventory_readiness: str = "same_bar"
    inventory_retention: str = "retained"
    active_booksize: float | None = None


@dataclass(frozen=True)
class EnhancedIndexConfig:
    lookthrough: Mapping[str, Mapping[str, float]]
    lower_bounds: Mapping[str, float]
    upper_bounds: Mapping[str, float]
    transaction_cost: Mapping[str, float]
    turnover_penalty: float = 0.0
    risk_penalty: float = 0.0
    cash_lower: float = 0.0
    cash_upper: float = 1.0
    solver: str = "CLARABEL"
