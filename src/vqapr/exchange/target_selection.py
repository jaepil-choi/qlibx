"""Internal exact execution-target selection, separate from the active fill convention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.domain.identifiers import ExecutionInputId
from vqapr.exchange.execution_table import ExecutionTableSpec, candidate_execution_instants

_IDENTITY_NAMESPACE = UUID("b560775c-9356-4be2-856f-85c8a85e1f15")


class TargetSelector(StrEnum):
    SAME_DAY = "SAME_DAY"
    NEXT_ELIGIBLE = "NEXT_ELIGIBLE"


@dataclass(frozen=True, slots=True)
class ExactTargetConvention:
    """The successor target authority; it intentionally does not reuse FillConvention."""

    selector: TargetSelector
    local_time: time
    timezone: str
    trade_price: str

    def __post_init__(self) -> None:
        if not isinstance(self.selector, TargetSelector):
            raise TypeError("selector must be a TargetSelector")
        if not isinstance(self.local_time, time) or self.local_time.tzinfo is not None:
            raise ValueError("local_time must be a timezone-naive datetime.time")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from exc
        if not isinstance(self.trade_price, str) or not self.trade_price.strip():
            raise ValueError("trade_price must be a non-empty semantic price field")


@dataclass(frozen=True, slots=True)
class ExactExecutionTarget:
    """A deterministic identity for one selected instant and exactly one price binding."""

    identity: UUID
    execution_input_id: ExecutionInputId
    target_at: datetime
    selector: TargetSelector
    trade_price: str


def resolve_exact_target(
    spec: ExecutionTableSpec,
    *,
    execution_input_id: ExecutionInputId,
    convention: ExactTargetConvention,
    decision_time: datetime,
    end_time: datetime,
) -> ExactExecutionTarget | None:
    """Resolve one strictly later target, returning no target rather than falling back."""

    if not isinstance(execution_input_id, str) or not execution_input_id:
        raise ValueError("execution_input_id must be a non-empty string")
    if not isinstance(convention, ExactTargetConvention):
        raise TypeError("convention must be an ExactTargetConvention")
    if decision_time.tzinfo is None or end_time.tzinfo is None:
        raise ValueError("decision_time and end_time must be timezone-aware")
    candidates = candidate_execution_instants(spec, decision_time=decision_time, end_time=end_time)
    zone = ZoneInfo(convention.timezone)
    if convention.selector is TargetSelector.SAME_DAY:
        decision_date = decision_time.astimezone(zone).date()
        candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.astimezone(zone).date() == decision_date
            and candidate.astimezone(zone).time() == convention.local_time
        )
    else:
        candidates = tuple(
            candidate
            for candidate in candidates
            if candidate.astimezone(zone).time() == convention.local_time
        )
    if not candidates:
        return None
    target_at = candidates[0].astimezone(UTC)
    identity = uuid5(
        _IDENTITY_NAMESPACE,
        "|".join(
            (
                str(execution_input_id),
                convention.selector.value,
                convention.timezone,
                convention.local_time.isoformat(),
                convention.trade_price,
                target_at.isoformat(),
            )
        ),
    )
    return ExactExecutionTarget(
        identity=identity,
        execution_input_id=execution_input_id,
        target_at=target_at,
        selector=convention.selector,
        trade_price=convention.trade_price,
    )
