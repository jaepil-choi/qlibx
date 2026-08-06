"""Machine-readable operation outcomes and failures."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import Field

from qlibx.models import QlibxModel


class OutcomeStatus(StrEnum):
    """Terminal status of an invoked operation."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class CommitStatus(StrEnum):
    """Whether an operation crossed an authoritative commit boundary."""

    NONE = "NONE"
    COMMITTED = "COMMITTED"


class OperationError(QlibxModel):
    """Bounded, serializable evidence for an operation failure."""

    operation: str = Field(min_length=1)
    stage_path: str = Field(min_length=1)
    error_code: str = Field(min_length=1)
    requirement_id: str | None = None
    expected: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    commit_status: CommitStatus = CommitStatus.NONE
    retry_preconditions: tuple[str, ...] = ()
    idempotency_identity: str = Field(min_length=1)
    error_id: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """Internal result carrier with explicit terminal status."""

    status: OutcomeStatus
    result: object | None = None
    diagnostics: tuple[object, ...] = ()
    errors: tuple[OperationError, ...] = ()

    def __post_init__(self) -> None:
        if self.status is OutcomeStatus.COMPLETE and self.errors:
            raise ValueError("a complete outcome cannot contain errors")
        if self.status in {OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED} and not self.errors:
            raise ValueError(f"a {self.status.value} outcome requires error evidence")
