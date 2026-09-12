"""What a venue did with an order batch, and the ledger entries it makes.

A `Fill` carries the requested, sized and dealt quantity, the price, the cost and the category it
was charged as. A name the venue did not fill carries one of four reasons -- `absent` (not on the
venue at that instant), `nontradable`, `no_trade` (a zero delta) or `unfunded` (the cash went to
earlier orders) -- and is never disguised as a fill.

`fill_entries` is the producer's half of the ledger contract: the fill already proved its numbers
agree with each other, and the account is handed the resulting deltas and asks nothing further.

**When a decision fills** is also a fill's fact. `FillRule`: a decision made at `D` fills at the
first market-clock instant strictly later than `D`; `at` keeps only the instants whose venue-local
wall time is that one, `after` sets a minimum elapsed time and `within` a maximum gap (a decision
with no candidate inside it has no target, which preflight refuses). `after` and `within` are
wall-clock durations, so a weekend counts in full. The candidate instants are an
`ExecutionHorizon` -- the execution table's instants inside the run, read once by
`data/execution_table.py` and bisected per decision; nothing here reads a file.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from vqapr.domain.account import FILL_ORIGIN, LedgerEntry
from vqapr.domain.cost import FillCost
from vqapr.domain.identifiers import DatasetId
from vqapr.domain.instants import iana_zone
from vqapr.domain.instrument import InstrumentKind
from vqapr.domain.order import OrderBatch

__all__ = [
    "_DURATION",
    "_IDENTITY_NAMESPACE",
    "_UNIT",
    "ExactExecutionTarget",
    "ExecutionHorizon",
    "Fill",
    "FillBatch",
    "FillRule",
    "ZeroDealtReason",
    "_instants",
    "fill_entries",
    "parse_duration",
]


class ZeroDealtReason(StrEnum):
    """Facts that result in an accepted order with no execution.

    The first three are facts about the MARKET: the venue published no row, published one saying
    the name could not trade, or the plan asked for no change. `UNFUNDED` is a fact about the
    ACCOUNT, and it is named separately for that reason -- a reader summing zero-dealt orders to
    ask "what did the market refuse me" must not have their own empty purse counted in the answer.
    """

    ABSENT = "absent"
    NONTRADABLE = "nontradable"
    NO_TRADE = "no_trade"
    UNFUNDED = "unfunded"
    """The batch ran out of cash before reaching this buy.

    Only a venue profile that charges and rounds to whole units can produce this. A fractional
    profile sizes exactly to the cash it has, so there is no residual for the money to run out
    against.
    """


def _decimal(value: Decimal, *, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class Fill:
    """The result for exactly one requested instrument."""

    instrument_id: str
    requested_quantity: Decimal
    dealt_quantity: Decimal
    price: Decimal | None
    reason: ZeroDealtReason | None = None
    cost: FillCost = field(default_factory=FillCost)
    kind: InstrumentKind | None = None
    """The category this fill was charged as, or ``None`` when the venue declared none.

    Carried on the fill rather than looked up afterwards because a fill is *evidence*: it records
    what the venue actually charged it as, and a roster edited later must not change what a past
    fill says it paid. It is also what lets a consumer that has no ``ExchangeRulesView`` -- a run
    record, a report -- separate an ETF sleeve's cost from the direct book's.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if self.kind is not None and not isinstance(self.kind, InstrumentKind):
            raise TypeError("kind must be an InstrumentKind or None")
        _decimal(self.requested_quantity, name="requested_quantity")
        _decimal(self.dealt_quantity, name="dealt_quantity")
        if not isinstance(self.cost, FillCost):
            raise TypeError("cost must be a FillCost")
        if self.price is not None:
            _decimal(self.price, name="price")
            if self.price <= 0:
                raise ValueError("price must be positive")
        if self.dealt_quantity == 0:
            if not isinstance(self.reason, ZeroDealtReason):
                raise ValueError("a zero-dealt fill must have a ZeroDealtReason")
            if self.price is not None:
                raise ValueError("a zero-dealt fill must not have a price")
            if self.cost.total != 0:
                raise ValueError("a zero-dealt fill must not charge a cost")
            return
        if self.reason is not None:
            raise ValueError("a dealt fill must not have a zero-dealt reason")
        if self.price is None:
            raise ValueError("a dealt fill must have a price")
        if self.requested_quantity == 0:
            raise ValueError("a dealt fill requires a non-zero requested quantity")
        if self.requested_quantity * self.dealt_quantity < 0:
            raise ValueError("dealt_quantity must have the requested quantity's sign")
        if abs(self.dealt_quantity) > abs(self.requested_quantity):
            raise ValueError("dealt_quantity cannot exceed requested_quantity")

    @classmethod
    def zero_dealt(
        cls, instrument_id: str, requested_quantity: Decimal, reason: ZeroDealtReason
    ) -> Fill:
        """An accepted order the venue did not execute, for the stated market or account fact.

        Every profile writes this same fill -- no price, no cost, nothing dealt -- for each of the
        `ZeroDealtReason` facts, and did so as five positional arguments repeated in two venues.
        One constructor keeps the shape of "nothing happened" in one place, so a venue adding a
        reason cannot spell the evidence differently from the others.
        """
        return cls(instrument_id, requested_quantity, Decimal("0"), None, reason)

    @property
    def notional(self) -> Decimal:
        """The absolute traded value before cost."""
        if self.price is None:
            return Decimal("0")
        return abs(self.dealt_quantity) * self.price

    @property
    def cash_delta(self) -> Decimal:
        """The exact signed cash movement this fill causes, cost included."""
        if self.price is None:
            return Decimal("0")
        return -(self.dealt_quantity * self.price) - self.cost.total


@dataclass(frozen=True, slots=True)
class FillBatch:
    """One complete exchange result, tied to the account state it observed."""

    fills: tuple[Fill, ...]
    account_version_seen: int

    def __post_init__(self) -> None:
        if not isinstance(self.fills, tuple) or any(
            not isinstance(fill, Fill) for fill in self.fills
        ):
            raise TypeError("fills must be a tuple of Fill")
        if isinstance(self.account_version_seen, bool) or not isinstance(
            self.account_version_seen, int
        ):
            raise TypeError("account_version_seen must be an integer")
        if self.account_version_seen < 0:
            raise ValueError("account_version_seen must be non-negative")
        instruments = tuple(fill.instrument_id for fill in self.fills)
        if len(instruments) != len(set(instruments)):
            raise ValueError("a FillBatch may contain each instrument only once")


def fill_entries(
    at: datetime, fills: FillBatch, orders: OrderBatch | None = None
) -> tuple[LedgerEntry, ...]:
    """The entries one fill batch makes, one per fill, in the batch's own order.

    The producer's half of §5.2: the venue said what each fill dealt at what price and cost, and
    `Fill` already proved those agree with each other. The ledger is handed the resulting deltas
    and the facts a reader of `vqapr.fill` needs, and asks nothing further.

    `orders` is the batch the fills answer. Each fill's `sized_quantity` -- what its weight sized
    to before the planner cut buys to the cash -- is read from it here, once, for every venue
    (record `261`); without it the value is `None`.
    """
    if not isinstance(fills, FillBatch):
        raise TypeError("fills must be a FillBatch")
    sized = (
        {}
        if orders is None
        else {request.instrument_id: request.sized_quantity for request in orders.requests}
    )
    return tuple(_fill_entry(at, fill, sized.get(fill.instrument_id)) for fill in fills.fills)


def _fill_entry(at: datetime, fill: Fill, sized: Decimal | None) -> LedgerEntry:
    dealt = fill.dealt_quantity
    return LedgerEntry(
        at=at,
        cash=fill.cash_delta,
        positions={fill.instrument_id: dealt} if dealt != 0 else {},
        origin=FILL_ORIGIN,
        detail={
            "instrument": fill.instrument_id,
            "requested_quantity": str(fill.requested_quantity),
            "sized_quantity": None if sized is None else str(sized),
            "dealt_quantity": str(dealt),
            "price": None if fill.price is None else str(fill.price),
            "commission": str(fill.cost.commission),
            "tax": str(fill.cost.tax),
            "reason": None if fill.reason is None else str(fill.reason),
            "kind": None if fill.kind is None else str(fill.kind),
        },
    )


_IDENTITY_NAMESPACE = UUID("b560775c-9356-4be2-856f-85c8a85e1f15")


_DURATION = re.compile(r"^(?P<count>[1-9]\d*)(?P<unit>[mhd])$")


_UNIT = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}


def parse_duration(text: str, *, name: str) -> timedelta:
    """`10m`, `2h`, `1d` -- a count and one of three units, the grammar `schedule.every` shares."""
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

    @classmethod
    def of(cls, candidates: Iterable[object]) -> ExecutionHorizon:
        """A horizon from the instants a scan answered: normalised to UTC and sorted."""
        return cls(tuple(sorted(_instants(candidates))))

    @classmethod
    def between(
        cls, instants: Iterable[datetime], *, start_time: datetime, end_time: datetime
    ) -> ExecutionHorizon:
        """The horizon `FillRule.build_horizon` would scan, cut from instants already read.

        `scan.candidate_instants` answers `trade_at > start AND trade_at <= end`, distinct and
        ascending; this is the same cut over the table's distinct instants when a caller already
        holds them (the workspace reads them once per command to derive the run's schedule, record
        `238`), so preflight and the judgments build the horizon without a second and third scan.
        """
        start_utc = start_time.astimezone(UTC)
        end_utc = end_time.astimezone(UTC)
        return cls(
            tuple(
                sorted(
                    instant
                    for instant in _instants(instants)
                    if start_utc < instant <= end_utc
                )
            )
        )


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
        iana_zone(self.timezone)
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

    def select_target(
        self,
        *,
        dataset_id: DatasetId,
        decision_time: datetime,
        end_time: datetime,
        horizon: ExecutionHorizon,
    ) -> ExactExecutionTarget | None:
        """The first market-clock instant after the decision that the rule admits, or `None`.

        `None` is a fact about the table and the rule -- no instant after this decision passes
        `at`/`after` inside `within` and the run's end -- and preflight proves it never happens
        for a frozen schedule (`_validate_execution_targets`). `horizon` is the
        execution table's candidate instants, read by `data/execution_table.py`, and `dataset_id`
        the dataset the target is stamped with.
        """
        if decision_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("decision_time and end_time must be timezone-aware")
        decision_utc = decision_time.astimezone(UTC)
        end_utc = end_time.astimezone(UTC)
        if decision_utc > end_utc:
            raise ValueError("decision_time must not be after end_time")

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
