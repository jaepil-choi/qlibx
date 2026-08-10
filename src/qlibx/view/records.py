"""Immutable input projections and observed-access lineage records."""

from datetime import datetime
from typing import Any, Protocol, TypeVar

from pydantic import Field

from qlibx.data.contracts import Lookback
from qlibx.models import QlibxModel


class ViewAccessError(RuntimeError):
    """Raised when code requests an undeclared or stale binding."""


class ArtifactViewAccessError(ViewAccessError):
    """Typed Strategy artifact access failure translated by the owning Flow."""

    def __init__(self, error_code: str, context: dict[str, Any]) -> None:
        self.error_code = error_code
        self.context = context
        super().__init__(str(context.get("message", error_code)))


class ArtifactInputProjection(QlibxModel):
    """Backend-free immutable artifact payload injected into a Strategy view."""

    requirement_id: str = Field(min_length=1)
    consumer_role: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    content_hash: str = Field(min_length=1)
    payload: QlibxModel


class ExecutionInputProjection(QlibxModel):
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    content_hash: str = Field(min_length=1)
    payload: QlibxModel


class ExecutionAccessRecord(QlibxModel):
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    content_hash: str = Field(min_length=1)


class ArtifactAccessRecord(QlibxModel):
    requirement_id: str = Field(min_length=1)
    consumer_role: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    artifact_schema_version: int = Field(ge=1)
    content_hash: str = Field(min_length=1)


PayloadModel = TypeVar("PayloadModel", bound=QlibxModel)


class AccessRecord(QlibxModel):
    dataset_id: str
    registration_identity: str
    semantic_role: str
    selected_field: str
    as_of: datetime
    row_count: int = Field(ge=0)
    max_available_at: datetime | None = None
    max_observation_time: datetime | None = None
    lookback: Lookback | None = None
    snapshot_fingerprint: str | None = None
    requested_instruments: tuple[str, ...] = ()
    per_instrument_actual_count: tuple[tuple[str, int], ...] = ()


class StateHolding(QlibxModel):
    instrument_id: str
    quantity: float
    mark: float | None = None
    marked_at: datetime | None = None


class StateAccessRecord(QlibxModel):
    account_id: str
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)
    cash: float
    nav: float
    valuation_status: str
    holdings: tuple[StateHolding, ...]
    as_of: datetime | None = None
    realized_pnl: tuple[tuple[str, float], ...] = ()


class AccountState(Protocol):
    account_id: str
    version: int
    feedback_cursor: int
    cash: float
    nav: float
    valuation_status: object
    positions: tuple[object, ...]
    as_of: datetime | None
    realized_pnl: tuple[tuple[str, float], ...]


class FeedbackAccessRecord(QlibxModel):
    account_id: str
    after_cursor: int = Field(ge=0)
    next_cursor: int = Field(ge=0)
    entry_cursors: tuple[int, ...]
    event_ids: tuple[str, ...]
    change_types: tuple[str, ...]
    fill_ids: tuple[str, ...]
    marked_instruments: tuple[str, ...]


class FeedbackMarkState(Protocol):
    instrument_id: str


class FeedbackEntryState(Protocol):
    cursor: int
    event_id: str
    change_type: str
    fill_ids: tuple[str, ...]
    marks: tuple[FeedbackMarkState, ...]


class AccountFeedbackState(Protocol):
    account_id: str
    after_cursor: int
    entries: tuple[FeedbackEntryState, ...]
    next_cursor: int


class SessionPerformanceAccessRecord(QlibxModel):
    artifact_id: str
    account_id: str
    event_id: str
    event_time: datetime
    feedback_cursor: int = Field(ge=0)


class SessionPerformanceRecordState(Protocol):
    account_id: str
    event_id: str
    event_time: datetime
    feedback_cursor: int


class PublishedSessionPerformanceState(Protocol):
    artifact_id: str
    record: SessionPerformanceRecordState


class MemoryAccessRecord(QlibxModel):
    strategy_id: str
    version: int = Field(ge=0)
    feedback_cursor: int = Field(ge=0)


class MemoryState(Protocol):
    strategy_id: str
    version: int
    value: object | None
    feedback_cursor: int


__all__ = [
    "AccessRecord",
    "AccountFeedbackState",
    "AccountState",
    "ArtifactAccessRecord",
    "ArtifactInputProjection",
    "ArtifactViewAccessError",
    "ExecutionAccessRecord",
    "ExecutionInputProjection",
    "FeedbackAccessRecord",
    "MemoryAccessRecord",
    "MemoryState",
    "PayloadModel",
    "PublishedSessionPerformanceState",
    "SessionPerformanceAccessRecord",
    "SessionPerformanceRecordState",
    "StateAccessRecord",
    "StateHolding",
    "ViewAccessError",
]
