"""Exchange가 고정하는 체결 시각과 가격 선택."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.data import scan
from vqapr.domain.identifiers import ExecutionInputId

_IDENTITY_NAMESPACE = UUID("b560775c-9356-4be2-856f-85c8a85e1f15")
_OFFSET = re.compile(r"[+-](?:0\d|1[0-4]):[0-5]\d\Z")


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
    fold: int | None = None
    offset: str | None = None

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
        if (self.fold is None) != (self.offset is None):
            raise ValueError("fold and offset must be declared together")
        if self.fold is not None and (
            not isinstance(self.fold, int) or isinstance(self.fold, bool) or self.fold not in (0, 1)
        ):
            raise ValueError("fold must be 0 or 1")
        if self.offset is not None:
            if not isinstance(self.offset, str) or _OFFSET.fullmatch(self.offset) is None:
                raise ValueError("offset must use ISO UTC offset format ±HH:MM")
            if self.offset[1:3] == "14" and self.offset[4:] != "00":
                raise ValueError("offset must be within ±14:00")

    @property
    def declaration_identity(self) -> tuple[str, str, str, str, int | None, str | None]:
        """Workspace-facing immutable selector declaration, including DST proof."""
        return (
            self.selector.value,
            self.local_time.isoformat(),
            self.timezone,
            self.trade_price,
            self.fold,
            self.offset,
        )

    def _local_target(self, day: date) -> datetime:
        """Resolve one venue-local candidate day without implicit DST policy."""
        zone = ZoneInfo(self.timezone)
        candidates: list[datetime] = []
        naive = datetime.combine(day, self.local_time)
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            round_trip = candidate.astimezone(UTC).astimezone(zone)
            if round_trip.replace(tzinfo=None) == naive and round_trip.fold == fold:
                candidates.append(candidate)
        if not candidates:
            raise ValueError(
                f"local target time {naive.isoformat()} does not exist in {self.timezone}"
            )
        if len(candidates) == 1:
            return candidates[0]
        if self.fold is None or self.offset is None:
            raise ValueError(
                f"local target time {naive.isoformat()} is ambiguous in {self.timezone}; "
                "declare fold and offset"
            )
        for candidate in candidates:
            offset = candidate.strftime("%z")
            formatted_offset = f"{offset[:3]}:{offset[3:]}"
            if candidate.fold == self.fold and formatted_offset == self.offset:
                return candidate
        raise ValueError(
            f"declared fold/offset does not resolve local target time {naive.isoformat()} "
            f"in {self.timezone}"
        )

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
        final_date = end_time.astimezone(zone).date()
        first_date = decision_date
        last_date = decision_date if self.selector is FillSelector.SAME_DAY else final_date
        day = first_date
        while day <= last_date:
            self._local_target(day)
            day += timedelta(days=1)
        for candidate in candidates:
            target_at = candidate.astimezone(UTC)
            local_candidate = target_at.astimezone(zone)
            resolved_local = self._local_target(local_candidate.date())
            if local_candidate.astimezone(UTC) != resolved_local.astimezone(UTC):
                continue
            if self.selector is FillSelector.SAME_DAY and local_candidate.date() != decision_date:
                continue
            identity = uuid5(
                _IDENTITY_NAMESPACE,
                "|".join(
                    (
                        str(execution_input.execution_input_id),
                        *(
                            "" if value is None else str(value)
                            for value in self.declaration_identity
                        ),
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
