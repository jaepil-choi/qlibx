"""Pydantic models for panel snapshots."""
from __future__ import annotations

import datetime as dt
import warnings
from typing import Any, Literal

from pydantic import BaseModel, Field

warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in .* shadows an attribute in parent "BaseModel"',
    category=UserWarning,
    module=__name__,
)


class CurvePoint(BaseModel):
    near_contract: str
    near_settle: float
    far_contract: str
    far_settle: float
    days_between: int


class InstrumentMeta(BaseModel):
    instrument_id: str
    sector: str
    multiplier: float
    tick: float
    margin_rate: float
    commission: float
    commission_type: str
    close_today_commission: float | None = None
    currency: Literal["RMB"] = "RMB"
    min_order_size: float = 1.0
    t_plus_one: bool = False
    stamp_duty_rate: float = 0.0
    transfer_fee_rate: float = 0.0
    min_commission: float = 0.0


class PanelManifest(BaseModel):
    schema: Literal["panel/v1", "panel/v3"] = "panel/v1"
    version: str
    created_at: str
    source_refs: list[str]
    calendar_start: dt.date
    calendar_end: dt.date
    instruments: list[str]
    files: dict[str, str] = Field(default_factory=dict)
    qc_report: str
    qc_status: Literal["PASS", "PASS_WITH_WARNINGS"]
    adjustment_convention: Literal["hfq_asof"] | None = None
    pit_status: Literal["ann_date_approx", "true_pit"] | None = None
    selection_date: dt.date | None = None


class QCCheck(BaseModel):
    check_id: str
    instrument: str | None = None
    date: dt.date | None = None
    severity: Literal["ERROR", "WARN"]
    message: str
    value: float | None = None
    waived: bool = False
    waiver_reason: str | None = None
    waiver_approved_by: str | None = None


class QCReport(BaseModel):
    schema: Literal["qc/v1"] = "qc/v1"
    snapshot: str
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    checks: list[QCCheck] = Field(default_factory=list)
    roll_gap_stats: dict[str, Any] = Field(default_factory=dict)
