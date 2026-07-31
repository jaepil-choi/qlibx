"""Pydantic portfolio models."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class PositionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lots: float
    avg_price: float
    contract: str
    margin_rmb: float


class BookState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    equity_rmb: float
    cash_rmb: float
    margin_used_rmb: float
    positions: dict[str, PositionState] = Field(default_factory=dict)


class TargetBook(BaseModel):
    """Absolute portfolio lots; an omitted instrument has target zero."""

    model_config = ConfigDict(extra="forbid")

    date: dt.date
    targets: dict[str, float] = Field(
        description=(
            "Absolute target lots by instrument. Instruments omitted from this "
            "mapping have an absolute target of zero."
        )
    )


class InstrumentRebalance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_scores: dict[str, float | None]
    blended: float
    vol_ann: float
    pre_round_lots: float
    post_round_lots: float
    caps_applied: list[dict[str, float | str]]


class RebalanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    instruments: dict[str, InstrumentRebalance]


class BookRiskSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    margin_used_rmb: float
    margin_utilization_pct: float
    gross_exposure_pct: float
    net_exposure_pct: float
    sector_gross_notional_pct: dict[str, float]
