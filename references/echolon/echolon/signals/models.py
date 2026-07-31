"""Pydantic models for signal scores."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ScoreVector(BaseModel):
    """Standardized per-instrument scores for one signal and date."""

    model_config = ConfigDict(extra="forbid")

    schema: Literal["scores/v1"] = "scores/v1"
    signal_id: str
    family: str
    date: dt.date
    scores: dict[str, float | None]

