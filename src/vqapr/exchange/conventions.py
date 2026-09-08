"""Exchange가 고정하는 체결 시각과 가격 선택."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
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


class ExecutionHorizon:
    """한 run 동안 불변인 체결 후보 시각 집합과, 해석이 끝난 venue-local target.

    `select_target`은 콜백마다 (1) 남은 horizon 전체의 instant를 다시 스캔하고
    (2) 남은 달력 전체를 순회하며 `_local_target`을 부르고 결과를 버렸다. 둘 다 **frozen run
    동안 변하지 않는 사실**이다. execution table은 run 내내 불변이므로 instant 집합도 불변이고,
    달력 해석은 순수 함수다.

    소유자는 run 수명 객체여야 한다. `FillConvention`은 값 객체라 상태를 들 수 없다.
    """

    __slots__ = ("_instants", "_local_targets", "_validated_through")

    def __init__(self, instants: tuple[datetime, ...]) -> None:
        self._instants = instants
        self._local_targets: dict[date, datetime] = {}
        self._validated_through: date | None = None

    @property
    def instants(self) -> tuple[datetime, ...]:
        return self._instants

    def after(self, decision_time: datetime) -> tuple[datetime, ...]:
        """Candidates strictly later than the decision, without rescanning the source."""
        return self._instants[bisect_right(self._instants, decision_time.astimezone(UTC)) :]

    def local_target(self, convention: FillConvention, day: date) -> datetime:
        cached = self._local_targets.get(day)
        if cached is None:
            cached = self._local_targets[day] = convention.resolve_local_target(day)
        return cached

    def validate_calendar(
        self, convention: FillConvention, *, first_date: date, last_date: date
    ) -> None:
        """Prove every venue-local target in the span resolves, once per run.

        The original loop re-proved the same days on every callback and discarded the result.
        The proof is a run-invariant fact, so it is kept instead of repeated.
        """
        start = first_date
        if self._validated_through is not None:
            if self._validated_through >= last_date:
                return
            start = max(start, self._validated_through + timedelta(days=1))
        day = start
        while day <= last_date:
            self.local_target(convention, day)
            day += timedelta(days=1)
        previous = self._validated_through
        self._validated_through = last_date if previous is None else max(previous, last_date)


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

    def resolve_local_target(self, day: date) -> datetime:
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

    def build_horizon(
        self,
        source: SourceSpec,
        *,
        trade_at_field: str,
        start_time: datetime,
        end_time: datetime,
        session: object | None = None,
    ) -> ExecutionHorizon:
        """Read the run's candidate instants once from an execution table's source.

        A convention reads a source and the field that stamps a fill; it does not know the
        registration that pairs it with a table. `ExecutionInputRegistration.build_horizon`
        passes its own table's binding here (one-shape Step 7, record 162: this was the
        `conventions <-> execution_table` import cycle).

        The execution table is frozen for the run, so this set cannot change between callbacks.
        `start_time` must not be later than the earliest decision the run will make, or the
        horizon would omit instants a callback is entitled to select.
        """
        if not isinstance(source, SourceSpec):
            raise TypeError("source must be a SourceSpec")
        candidates = scan.candidate_instants(
            source,
            trade_at_field=trade_at_field,
            decision_time=start_time,
            end_time=end_time,
            session=session,
        )
        return ExecutionHorizon(
            tuple(sorted(candidate.astimezone(UTC) for candidate in candidates))
        )

    def select_target(
        self,
        source: SourceSpec,
        *,
        trade_at_field: str,
        execution_input_id: ExecutionInputId,
        decision_time: datetime,
        end_time: datetime,
        horizon: ExecutionHorizon | None = None,
    ) -> ExactExecutionTarget | None:
        """Select the first strictly-later eligible execution instant in the run horizon.

        `source`/`trade_at_field` are the execution table's binding and `execution_input_id` the
        registration the target is stamped with; a registration passes its own through
        `ExecutionInputRegistration.select_target`.
        """

        if not isinstance(source, SourceSpec):
            raise TypeError("source must be a SourceSpec")
        if decision_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("decision_time and end_time must be timezone-aware")
        if decision_time.astimezone(UTC) > end_time.astimezone(UTC):
            raise ValueError("decision_time must not be after end_time")

        if horizon is None:
            candidates = scan.candidate_instants(
                source,
                trade_at_field=trade_at_field,
                decision_time=decision_time,
                end_time=end_time,
            )
            candidates = tuple(candidate.astimezone(UTC) for candidate in candidates)
            resolve = self.resolve_local_target
        else:
            # The horizon was read once for the whole run; bisect to this decision instead of
            # rescanning, and drop anything past this call's own end_time.
            end_utc = end_time.astimezone(UTC)
            candidates = tuple(
                candidate for candidate in horizon.after(decision_time) if candidate <= end_utc
            )

            def resolve(day: date) -> datetime:
                return horizon.local_target(self, day)

        zone = ZoneInfo(self.timezone)
        decision_date = decision_time.astimezone(zone).date()
        final_date = end_time.astimezone(zone).date()
        first_date = decision_date
        last_date = decision_date if self.selector is FillSelector.SAME_DAY else final_date
        if horizon is None:
            day = first_date
            while day <= last_date:
                self.resolve_local_target(day)
                day += timedelta(days=1)
        else:
            horizon.validate_calendar(self, first_date=first_date, last_date=last_date)
        for candidate in candidates:
            target_at = candidate.astimezone(UTC)
            local_candidate = target_at.astimezone(zone)
            resolved_local = resolve(local_candidate.date())
            if local_candidate.astimezone(UTC) != resolved_local.astimezone(UTC):
                continue
            if self.selector is FillSelector.SAME_DAY and local_candidate.date() != decision_date:
                continue
            identity = uuid5(
                _IDENTITY_NAMESPACE,
                "|".join(
                    (
                        str(execution_input_id),
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
                execution_input_id=execution_input_id,
                target_at=target_at,
                selector=self.selector,
                trade_price=self.trade_price,
            )
        return None
