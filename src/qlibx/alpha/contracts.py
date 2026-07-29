"""Value objects shared by the operation registry and every operation implementation.

Kept separate from ``registry`` so an operation module can import the contract it
produces without importing the dispatch machinery that calls it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

NEUTRALITY_WARNING = (
    "A transform is not proof of exact market, benchmark, industry, sector, or factor neutrality."
)


@dataclass(frozen=True, slots=True)
class OperationContract:
    """Versioned semantics of one applied operation; becomes result lineage."""

    operation_id: str
    version: str
    axis: str
    tie_behavior: str
    nan_behavior: str
    minimum_observations: int | None
    group_missing_behavior: str
    dtype: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    summary: str = ""
    selection_behavior: str = "not_applicable"
    implementation: str = "builtin"
    implementation_digest: str | None = None


@dataclass(frozen=True, slots=True)
class TransformResult:
    values: pd.DataFrame
    lineage: tuple[OperationContract, ...]
    neutrality_warning: str | None = None


__all__ = ["NEUTRALITY_WARNING", "OperationContract", "TransformResult"]
