"""Exchange가 고정하는 체결 시각과 가격 선택."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.data import scan
from vqapr.domain.identifiers import ExecutionInputId

_IDENTITY_NAMESPACE = UUID("b560775c-9356-4be2-856f-85c8a85e1f15")


class FillSelector(StrEnum):
    """The venue-local rule used to select an execution snapshot."""

    SAME_DAY = "SAME_DAY"
    NEXT_ELIGIBLE = "NEXT_ELIGIBLE"


@dataclass(frozen=True, slots=True)
class ExactExecutionTarget:
    """A deterministic selected instant and its unambiguous price binding."""

    identity: UUID
    execution_input_id: ExecutionInputId
    target_at: datetime
    selector: FillSelector
    trade_price: str


@dataclass(frozen=True, slots=True)
class FillConvention:
    """한 decision을 어느 session 시각의 어느 execution field로 체결할지 선언한다."""

    selector: FillSelector
    local_time: time
    timezone: str
    trade_price: str

    def __post_init__(self) -> None:
        if not isinstance(self.selector, FillSelector):
            raise TypeError("selector must be a FillSelector")
        if not isinstance(self.local_time, time):
            raise TypeError("local_time must be a datetime.time")
        if self.local_time.tzinfo is not None:
            raise ValueError("local_time must be a timezone-naive wall time")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from error
        if not isinstance(self.trade_price, str) or not self.trade_price.strip():
            raise ValueError("trade_price must be a non-empty semantic price field")

    def select_target(
        self,
        execution_input: object,
        *,
        decision_time: datetime,
        end_time: datetime,
    ) -> ExactExecutionTarget | None:
        """Select the first strictly-later eligible execution instant in the run horizon."""

        from vqapr.exchange.execution_table import ExecutionInputRegistration

        if not isinstance(execution_input, ExecutionInputRegistration):
            raise TypeError("execution_input must be an ExecutionInputRegistration")
        if decision_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("decision_time and end_time must be timezone-aware")
        if decision_time.astimezone(UTC) > end_time.astimezone(UTC):
            raise ValueError("decision_time must not be after end_time")

        table = execution_input.table
        candidates = scan.candidate_instants(
            table.source,
            trade_at_field=table.trade_at_field,
            decision_time=decision_time,
            end_time=end_time,
        )
        zone = ZoneInfo(self.timezone)
        decision_date = decision_time.astimezone(zone).date()
        for candidate in candidates:
            target_at = candidate.astimezone(UTC)
            local_candidate = target_at.astimezone(zone)
            if local_candidate.time() != self.local_time:
                continue
            if self.selector is FillSelector.SAME_DAY and local_candidate.date() != decision_date:
                continue
            identity = uuid5(
                _IDENTITY_NAMESPACE,
                "|".join(
                    (
                        str(execution_input.execution_input_id),
                        self.selector.value,
                        self.timezone,
                        self.local_time.isoformat(),
                        self.trade_price,
                        target_at.isoformat(),
                    )
                ),
            )
            return ExactExecutionTarget(
                identity=identity,
                execution_input_id=execution_input.execution_input_id,
                target_at=target_at,
                selector=self.selector,
                trade_price=self.trade_price,
            )
        return None
