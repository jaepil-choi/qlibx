"""When a decision fills: the first market-clock instant after it, and three optional handles.

Design §3.5. The market clock is every instant the execution table has (§3); a decision made at
`D` fills at the first of them strictly later than `D`. That default already expresses a
minute-by-minute strategy on a minute table -- the next point is the next minute -- and a daily
strategy on a daily table. Three handles narrow it:

    at       keep only the instants whose venue-local wall time is this one   ("fill at the close")
    after    a minimum elapsed time since the decision                         (delayed fill)
    within   a maximum gap; a decision with no candidate inside it has no target, which
             preflight refuses                                     ("fill today or not at all")

What retired with this module's previous shape: the `SAME_DAY` / `NEXT_ELIGIBLE` selector (the
difference -- "may it roll to the next day" -- is `within`), the fill's own `timezone` (the run's
zone reads `at`), and the fold/offset proof (`at` FILTERS real instants by their clock reading
rather than constructing a wall time, so an instant that happens twice is two candidates and the
first later one wins; a wall time that never happens simply matches nothing).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr.data import scan
from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import DatasetId

_IDENTITY_NAMESPACE = UUID("b560775c-9356-4be2-856f-85c8a85e1f15")
_DURATION = re.compile(r"^(?P<count>[1-9]\d*)(?P<unit>[mhd])$")
_UNIT = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}


def parse_duration(text: str, *, name: str) -> timedelta:
    """`10m`, `2h`, `1d` -- a count and one of three units, the grammar `agenda.every` shares."""
    match = _DURATION.match(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"{name} must be a count and a unit such as 10m, 2h or 1d; got {text!r}")
    return int(match.group("count")) * _UNIT[match.group("unit")]


def _instants(candidates: Iterable[object]) -> tuple[datetime, ...]:
    """The scan's candidate instants, normalised to UTC.

    The scan reads a `TIMESTAMPTZ` column and hands the values back untyped; anything that is not
    a datetime is a table whose declared trade-at field is not one, and that is refused by name
    rather than left to fail on the first attribute read.
    """
    instants: list[datetime] = []
    for candidate in candidates:
        if not isinstance(candidate, datetime):
            raise TypeError(f"execution instant must be a datetime, got {type(candidate).__name__}")
        instants.append(candidate.astimezone(UTC))
    return tuple(instants)


@dataclass(frozen=True, slots=True)
class ExactExecutionTarget:
    """A deterministic selected instant and its unambiguous price binding."""

    identity: UUID
    dataset_id: DatasetId
    target_at: datetime
    trade_price: str


class ExecutionHorizon:
    """The run's candidate instants, read once and bisected per decision.

    The execution table is frozen for the run, so this set cannot change between callbacks;
    rescanning it per callback was the cost record `162` removed. The owner is a run-lifetime
    object because `FillRule` is a value and holds no state.
    """

    __slots__ = ("_instants",)

    def __init__(self, instants: tuple[datetime, ...]) -> None:
        self._instants = instants

    @property
    def instants(self) -> tuple[datetime, ...]:
        return self._instants

    def after(self, decision_time: datetime) -> tuple[datetime, ...]:
        """Candidates strictly later than the decision, without rescanning the source."""
        return self._instants[bisect_right(self._instants, decision_time.astimezone(UTC)) :]


@dataclass(frozen=True, slots=True)
class FillRule:
    """Which market-clock instant a decision fills at, and at which price (design §3.5)."""

    trade_price: str
    timezone: str
    at: time | None = None
    after: str | None = None
    within: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trade_price, str) or not self.trade_price.strip():
            raise ValueError("trade_price must be a non-empty semantic price field")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from error
        if self.at is not None:
            if not isinstance(self.at, time):
                raise TypeError("at must be a datetime.time")
            if self.at.tzinfo is not None:
                raise ValueError("at must be a timezone-naive wall time; the run declares the zone")
        if self.after is not None:
            parse_duration(self.after, name="after")
        if self.within is not None:
            parse_duration(self.within, name="within")
        if self.after is not None and self.within is not None:
            minimum = parse_duration(self.after, name="after")
            if minimum > parse_duration(self.within, name="within"):
                raise ValueError("after must not exceed within: no instant could satisfy both")

    @property
    def declaration_identity(self) -> tuple[str, str, str, str, str]:
        """Workspace-facing immutable declaration of the rule."""
        return (
            self.trade_price,
            self.timezone,
            "" if self.at is None else self.at.isoformat(),
            self.after or "",
            self.within or "",
        )

    def describe(self) -> str:
        parts = ["the first execution instant after the decision"]
        if self.at is not None:
            parts.append(f"at {self.at.isoformat()} {self.timezone}")
        if self.after is not None:
            parts.append(f"at least {self.after} later")
        if self.within is not None:
            parts.append(f"within {self.within}")
        return ", ".join(parts)

    def build_horizon(
        self,
        source: SourceSpec,
        *,
        trade_at_field: str,
        start_time: datetime,
        end_time: datetime,
        session: scan.ScanSession | None = None,
    ) -> ExecutionHorizon:
        """Read the run's candidate instants once from an execution table's source.

        A rule reads a source and the field that stamps a fill; it does not know the
        registration that pairs it with a table. `ExecutionTable.build_horizon` passes its own
        table's binding here (record `162`). `start_time` must not be later than the earliest
        decision the run will make, or the horizon would omit instants a callback is entitled to.
        """
        candidates = scan.candidate_instants(
            source,
            trade_at_field=trade_at_field,
            decision_time=start_time,
            end_time=end_time,
            session=session,
        )
        return ExecutionHorizon(tuple(sorted(_instants(candidates))))

    def select_target(
        self,
        source: SourceSpec,
        *,
        trade_at_field: str,
        dataset_id: DatasetId,
        decision_time: datetime,
        end_time: datetime,
        horizon: ExecutionHorizon | None = None,
    ) -> ExactExecutionTarget | None:
        """The first market-clock instant after the decision that the rule admits, or `None`.

        `None` is a fact about the table and the rule -- no instant after this decision passes
        `at`/`after` inside `within` and the run's end -- and preflight proves it never happens
        for a frozen agenda (`_validate_execution_targets`). `source`/`trade_at_field` are the
        execution table's binding and `dataset_id` the dataset the target is stamped with.
        """
        if decision_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("decision_time and end_time must be timezone-aware")
        decision_utc = decision_time.astimezone(UTC)
        end_utc = end_time.astimezone(UTC)
        if decision_utc > end_utc:
            raise ValueError("decision_time must not be after end_time")

        if horizon is None:
            candidates = _instants(
                scan.candidate_instants(
                    source,
                    trade_at_field=trade_at_field,
                    decision_time=decision_time,
                    end_time=end_time,
                )
            )
        else:
            candidates = horizon.after(decision_time)
        earliest = decision_utc if self.after is None else (
            decision_utc + parse_duration(self.after, name="after")
        )
        latest = end_utc if self.within is None else min(
            end_utc, decision_utc + parse_duration(self.within, name="within")
        )
        zone = ZoneInfo(self.timezone)
        for candidate in candidates:
            target_at = candidate.astimezone(UTC)
            if target_at <= decision_utc or target_at < earliest:
                continue
            if target_at > latest:
                return None
            if self.at is not None and target_at.astimezone(zone).time() != self.at:
                continue
            identity = uuid5(
                _IDENTITY_NAMESPACE,
                "|".join((str(dataset_id), *self.declaration_identity, target_at.isoformat())),
            )
            return ExactExecutionTarget(
                identity=identity,
                dataset_id=dataset_id,
                target_at=target_at,
                trade_price=self.trade_price,
            )
        return None
