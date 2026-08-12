"""Declared session-level actual-state history contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from qlibx.data.contracts import RowsLookback
from qlibx.models import QlibxModel


class AccountHistoryShape(StrEnum):
    ACCOUNT_SERIES = "account_series"
    INSTRUMENT_PANEL = "instrument_panel"


class AccountSeriesField(StrEnum):
    CASH = "cash"
    NAV = "nav"
    REALIZED_PNL = "realized_pnl"
    GROSS_EXPOSURE = "gross_exposure"


class InstrumentPanelField(StrEnum):
    QUANTITY = "quantity"
    AVERAGE_COST = "average_cost"
    REALIZED_PNL = "realized_pnl"
    MARK = "mark"


class AccountHistoryRecordingSpec(QlibxModel):
    """Frozen user selection of actual-state fields retained during one run."""

    account_series_fields: tuple[AccountSeriesField, ...] = ()
    instrument_panel_fields: tuple[InstrumentPanelField, ...] = ()

    @model_validator(mode="after")
    def validate_unique_fields(self) -> "AccountHistoryRecordingSpec":
        if len(self.account_series_fields) != len(set(self.account_series_fields)):
            raise ValueError("account-series recording fields must be unique")
        if len(self.instrument_panel_fields) != len(set(self.instrument_panel_fields)):
            raise ValueError("instrument-panel recording fields must be unique")
        return self


class AccountHistoryRequirement(QlibxModel):
    """One Strategy-declared actual-state history window."""

    requirement_id: str = Field(min_length=1)
    shape: AccountHistoryShape
    fields: tuple[str, ...] = Field(min_length=1)
    lookback: RowsLookback
    instruments: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_shape_fields(self) -> "AccountHistoryRequirement":
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("actual-state history fields must be unique")
        allowed = (
            {item.value for item in AccountSeriesField}
            if self.shape is AccountHistoryShape.ACCOUNT_SERIES
            else {item.value for item in InstrumentPanelField}
        )
        unsupported = tuple(field for field in self.fields if field not in allowed)
        if unsupported:
            raise ValueError(
                f"fields {unsupported!r} are not valid for {self.shape.value}"
            )
        if self.shape is AccountHistoryShape.ACCOUNT_SERIES and self.instruments:
            raise ValueError("account-series history cannot declare instruments")
        if len(self.instruments) != len(set(self.instruments)):
            raise ValueError("actual-state history instruments must be unique")
        return self


class AccountSeriesHistoryRow(QlibxModel):
    kind: Literal["account_series"] = "account_series"
    session_time: datetime
    values: dict[str, float | None]


class InstrumentPanelHistoryRow(QlibxModel):
    kind: Literal["instrument_panel"] = "instrument_panel"
    session_time: datetime
    instrument_id: str = Field(min_length=1)
    values: dict[str, float | None]


AccountHistoryRow = AccountSeriesHistoryRow | InstrumentPanelHistoryRow


class AccountHistoryProjection(QlibxModel):
    """Immutable declared history made visible to one Strategy invocation."""

    requirement_id: str
    account_id: str
    shape: AccountHistoryShape
    selected_fields: tuple[str, ...]
    requested_rows: int = Field(gt=0)
    rows: tuple[AccountHistoryRow, ...]


class AccountHistoryAccessRecord(QlibxModel):
    requirement_id: str
    account_id: str
    shape: AccountHistoryShape
    selected_fields: tuple[str, ...]
    requested_rows: int = Field(gt=0)
    available_sessions: int = Field(ge=0)
    start_session: datetime | None = None
    end_session: datetime | None = None
    instruments: tuple[str, ...] = ()


__all__ = [
    "AccountHistoryAccessRecord",
    "AccountHistoryProjection",
    "AccountHistoryRecordingSpec",
    "AccountHistoryRequirement",
    "AccountHistoryRow",
    "AccountHistoryShape",
    "AccountSeriesField",
    "AccountSeriesHistoryRow",
    "InstrumentPanelField",
    "InstrumentPanelHistoryRow",
]