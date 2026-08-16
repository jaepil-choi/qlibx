"""Internal envelopes for deterministic static and due dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from vqapr.domain.timestamps import require_tz_aware
from vqapr.runtime.agendas import OperationOccurrence


@dataclass(frozen=True, slots=True)
class OperationEnvelope:
    """Internal static agenda item for the later merged dispatcher."""

    occurrence: OperationOccurrence

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")

    def sort_key(self) -> tuple[datetime, int, str]:
        return self.occurrence.sort_key()


@dataclass(frozen=True, slots=True)
class DueExecutionEnvelope:
    """Internal dynamic execution item.

    The negative priority deliberately orders an already-pending execution
    before every static operation at the same UTC instant.
    """

    due_time: datetime
    pending_id: str

    def __post_init__(self) -> None:
        require_tz_aware(self.due_time, name="due_time")
        if not isinstance(self.pending_id, str) or not self.pending_id:
            raise ValueError("pending_id must be a non-empty string")

    def sort_key(self) -> tuple[datetime, int, str]:
        return (self.due_time.astimezone(UTC), -1, self.pending_id)
