"""Agent-first run, account, execution, constraint, and publication declarations.

``vqapr.simulation`` is the sole public home for everything a caller declares to run and
publish a Strategy simulation: the execution input/fill convention, the strategy/valuation/
monitoring cadence, the initial account, the constraint bindings, the complete ``Simulation``
run declaration, and the ``Publication`` output selection. ``CompletedRun``/``PublishedRun`` are
not declared here — they carry G003 lifecycle behavior (an actual run/publish outcome) rather
than being pure immutable value contracts, so they belong with the lifecycle facade, not this
algebra module.

Every public declaration is a frozen, slotted, keyword-only value. Constructors reject empty or
duplicate identifiers, naive datetimes/wall times, unknown IANA timezones, non-finite Decimal
values, and out-of-order instants. Incoming mappings are copied into read-only, key-sorted views
so two callers cannot observe or mutate each other's declaration. This module declares algebra
only: no execution/account/constraint engine, store, or Project wiring lives here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vqapr import authoring, venues
from vqapr.domain.timestamps import require_tz_aware

__all__ = (
    "AccountMode",
    "AccountSnapshot",
    "AllocationOutput",
    "Cadence",
    "ConstraintDeclaration",
    "Execution",
    "ExecutionInput",
    "FillConvention",
    "FillSelector",
    "InitialAccount",
    "Publication",
    "RecordOutput",
    "Schedule",
    "Simulation",
)


# --------------------------------------------------------------------------------------
# Shared validation helpers (implementation detail; not part of the public algebra).
# --------------------------------------------------------------------------------------


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"{name} must be a non-empty string without whitespace")
    return value


def _unique_identifiers(values: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of strings")
    normalized = tuple(_identifier(value, name=f"{name} entry") for value in values)
    if not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} entries must be unique")
    return normalized


def _finite_decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _finite_nonnegative_decimal(value: object, *, name: str) -> Decimal:
    checked = _finite_decimal(value, name=name)
    if checked < 0:
        raise ValueError(f"{name} must be non-negative")
    return checked


def _tz_aware(value: object, *, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    return require_tz_aware(value, name=name)


def _wall_time(value: object, *, name: str) -> time:
    if not isinstance(value, time):
        raise TypeError(f"{name} must be a datetime.time")
    if value.tzinfo is not None:
        raise ValueError(f"{name} must be a timezone-naive wall time")
    return value


def _timezone_name(value: object, *, name: str = "timezone") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty IANA timezone name")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown IANA timezone: {value!r}") from error
    return value


def _sorted_unique_dates(values: object, *, name: str) -> tuple[date, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of dates")
    normalized: tuple[date, ...] = tuple(values)
    if not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    for entry in normalized:
        if not isinstance(entry, date) or isinstance(entry, datetime):
            raise TypeError(f"{name} entries must be date values")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} entries must be unique")
    if tuple(sorted(normalized)) != normalized:
        raise ValueError(f"{name} entries must be in ascending order")
    return normalized


def _path(value: object, *, name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{name} must be a pathlib.Path")
    return value


def _str_mapping(values: object, *, name: str, allow_empty: bool = False) -> Mapping[str, str]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, value in values.items():
        checked_key = _identifier(key, name=f"{name} key")
        if not isinstance(value, str) or not value or any(char.isspace() for char in value):
            raise ValueError(
                f"{name}[{checked_key!r}] must be a non-empty string without whitespace"
            )
        normalized[checked_key] = value
    if not allow_empty and not normalized:
        raise ValueError(f"{name} must contain at least one entry")
    return MappingProxyType(dict(sorted(normalized.items())))


def _canonical_scalar(value: object, *, name: str) -> object:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} float values must be finite")
        return value
    if isinstance(value, Decimal):
        return _finite_decimal(value, name=name)
    if isinstance(value, datetime):
        return _tz_aware(value, name=name)
    if isinstance(value, date):
        return value
    raise TypeError(f"{name} values must be portable scalars; got {type(value).__name__}")


def _canonical_config(value: object, *, name: str) -> object:
    """Recursively validate/normalize one declared config value into a detached view.

    Only portable scalars plus nested mapping/sequence are accepted, matching the same
    ``vqapr.config`` portability rule the framework applies to canonical identity encoding:
    no callable, path, set, bytes, or non-finite value may hide inside a declared config.
    """
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            checked_key = _identifier(key, name=f"{name} key")
            normalized[checked_key] = _canonical_config(item, name=f"{name}[{checked_key!r}]")
        return MappingProxyType(dict(sorted(normalized.items())))
    if isinstance(value, (list, tuple)):
        return tuple(
            _canonical_config(item, name=f"{name}[{index}]") for index, item in enumerate(value)
        )
    return _canonical_scalar(value, name=name)


# --------------------------------------------------------------------------------------
# Execution input and fill convention.
# --------------------------------------------------------------------------------------


class FillSelector(StrEnum):
    """The venue-local rule used to select an execution snapshot for a decision."""

    SAME_DAY = "SAME_DAY"
    NEXT_ELIGIBLE = "NEXT_ELIGIBLE"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionInput:
    """A caller's complete declaration of one registered execution-price source.

    ``input_id`` is an explicit human binding key a ``Simulation``'s ``Execution`` references;
    it is not an authority identity. ``price_fields`` maps semantic framework price names to
    physical source columns, mirroring ``project.DatasetDeclaration.fields`` — the framework
    cannot infer which physical column is the tradable price.
    """

    input_id: str
    path: Path
    hive_partitioned: bool
    trade_at_field: str
    instrument_field: str
    is_tradable_field: str
    price_fields: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_id", _identifier(self.input_id, name="input_id"))
        object.__setattr__(self, "path", _path(self.path, name="path"))
        if not isinstance(self.hive_partitioned, bool):
            raise TypeError("hive_partitioned must be a bool")
        object.__setattr__(
            self, "trade_at_field", _identifier(self.trade_at_field, name="trade_at_field")
        )
        object.__setattr__(
            self, "instrument_field", _identifier(self.instrument_field, name="instrument_field")
        )
        object.__setattr__(
            self,
            "is_tradable_field",
            _identifier(self.is_tradable_field, name="is_tradable_field"),
        )
        object.__setattr__(
            self, "price_fields", _str_mapping(self.price_fields, name="price_fields")
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FillConvention:
    """A caller's declaration of which session instant and price field fills a decision."""

    selector: FillSelector
    at: time
    timezone: str
    trade_price: str

    def __post_init__(self) -> None:
        if not isinstance(self.selector, FillSelector):
            raise TypeError("selector must be a FillSelector")
        object.__setattr__(self, "at", _wall_time(self.at, name="at"))
        object.__setattr__(self, "timezone", _timezone_name(self.timezone))
        object.__setattr__(self, "trade_price", _identifier(self.trade_price, name="trade_price"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Execution:
    """A Simulation's complete execution declaration: source input plus fill convention."""

    input: ExecutionInput
    fill: FillConvention

    def __post_init__(self) -> None:
        if not isinstance(self.input, ExecutionInput):
            raise TypeError("input must be an ExecutionInput")
        if not isinstance(self.fill, FillConvention):
            raise TypeError("fill must be a FillConvention")


# --------------------------------------------------------------------------------------
# Cadence and schedule.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Cadence:
    """One explicit, non-empty local occurrence calendar.

    ``sessions`` is the complete, explicit, ascending set of session dates this cadence fires
    on — there is no inferred trading calendar. ``at``/``timezone`` fix one venue-local wall
    time each session resolves to.
    """

    sessions: tuple[date, ...]
    at: time
    timezone: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sessions", _sorted_unique_dates(self.sessions, name="sessions"))
        object.__setattr__(self, "at", _wall_time(self.at, name="at"))
        object.__setattr__(self, "timezone", _timezone_name(self.timezone))


@dataclass(frozen=True, slots=True, kw_only=True)
class Schedule:
    """A Simulation's complete run calendar: strategy, valuation, optional monitoring, horizon.

    ``monitoring=None`` is a required explicit declaration that no monitoring cadence exists —
    it is never a default. ``start``/``end`` fix the run horizon that bounds every cadence.
    """

    strategy: Cadence
    valuation: Cadence
    monitoring: Cadence | None
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, Cadence):
            raise TypeError("strategy must be a Cadence")
        if not isinstance(self.valuation, Cadence):
            raise TypeError("valuation must be a Cadence")
        if self.monitoring is not None and not isinstance(self.monitoring, Cadence):
            raise TypeError("monitoring must be a Cadence or None")
        object.__setattr__(self, "start", _tz_aware(self.start, name="start"))
        object.__setattr__(self, "end", _tz_aware(self.end, name="end"))
        if self.end <= self.start:
            raise ValueError("end must be strictly after start")


# --------------------------------------------------------------------------------------
# Account declarations.
# --------------------------------------------------------------------------------------


class AccountMode(StrEnum):
    """The sole account-level position constraint for a run's Account."""

    LONG_ONLY = "long_only"
    SIGNED = "signed"


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountSnapshot:
    """A caller's declared initial account state: cash and any starting positions.

    A snapshot cannot expose or alias mutable Account authority; it is a plain immutable value.
    ``version`` starts a run's account version sequence and is normally ``0`` for a fresh run.
    """

    version: int
    cash: Decimal
    positions: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        object.__setattr__(self, "cash", _finite_nonnegative_decimal(self.cash, name="cash"))
        if not isinstance(self.positions, Mapping):
            raise TypeError("positions must be a mapping")
        normalized: dict[str, Decimal] = {}
        for instrument_id, quantity in self.positions.items():
            checked_id = _identifier(instrument_id, name="positions key")
            checked_quantity = _finite_decimal(quantity, name=f"positions[{checked_id!r}]")
            normalized[checked_id] = checked_quantity
        object.__setattr__(self, "positions", MappingProxyType(dict(sorted(normalized.items()))))

    @classmethod
    def cash_only(cls, amount: Decimal) -> AccountSnapshot:
        """A fresh, version-zero snapshot holding only ``amount`` of cash and no positions."""
        return cls(version=0, cash=amount, positions={})


@dataclass(frozen=True, slots=True, kw_only=True)
class InitialAccount:
    """A Simulation's complete starting Account declaration: snapshot plus position mode."""

    snapshot: AccountSnapshot
    mode: AccountMode

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AccountSnapshot):
            raise TypeError("snapshot must be an AccountSnapshot")
        if not isinstance(self.mode, AccountMode):
            raise TypeError("mode must be an AccountMode")
        if self.mode is AccountMode.LONG_ONLY and any(
            quantity < 0 for quantity in self.snapshot.positions.values()
        ):
            raise ValueError("a long_only account cannot declare a negative starting position")


# --------------------------------------------------------------------------------------
# Constraint binding.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstraintDeclaration:
    """One Constraint's binding into a Simulation, carried in ``Simulation.constraints``.

    ``constraint`` is annotated ``type[authoring.Constraint]``; this module never defines or
    re-exports ``Constraint`` itself — it names the single canonical home. ``name`` is
    non-empty human diagnostics text only and never enters identity.
    """

    constraint: type[authoring.Constraint]
    config: Mapping[str, object]
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.constraint, type) or not issubclass(
            self.constraint, authoring.Constraint
        ):
            raise TypeError("constraint must be a subclass of vqapr.authoring.Constraint")
        object.__setattr__(self, "config", _canonical_config(self.config, name="config"))
        object.__setattr__(self, "name", _identifier(self.name, name="name"))


# --------------------------------------------------------------------------------------
# Simulation declaration.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Simulation:
    """A caller's complete, explicit run declaration.

    Every field is required. ``constraints=()`` and ``initial_strategy_state=None`` are
    required explicit values distinguishing deliberate absence from omission — there is no
    default constraint set or default starting strategy state.
    """

    schedule: Schedule
    execution: Execution
    exchange: venues.Academic
    account: InitialAccount
    constraints: tuple[ConstraintDeclaration, ...]
    instruments: tuple[str, ...]
    initial_strategy_state: object

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, Schedule):
            raise TypeError("schedule must be a Schedule")
        if not isinstance(self.execution, Execution):
            raise TypeError("execution must be an Execution")
        if not isinstance(self.exchange, venues.Academic):
            raise TypeError("exchange must be a venues.Academic")
        if not isinstance(self.account, InitialAccount):
            raise TypeError("account must be an InitialAccount")
        if not isinstance(self.constraints, tuple) or any(
            not isinstance(entry, ConstraintDeclaration) for entry in self.constraints
        ):
            raise TypeError("constraints must be a tuple of ConstraintDeclaration")
        names = tuple(entry.name for entry in self.constraints)
        if len(set(names)) != len(names):
            raise ValueError("constraints must not repeat a declaration name")
        object.__setattr__(
            self, "instruments", _unique_identifiers(self.instruments, name="instruments")
        )
        object.__setattr__(
            self,
            "initial_strategy_state",
            _canonical_config(self.initial_strategy_state, name="initial_strategy_state")
            if self.initial_strategy_state is not None
            else None,
        )


# --------------------------------------------------------------------------------------
# Publication declarations.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class AllocationOutput:
    """A caller's selection of one dataset/field to publish the run's target allocation to."""

    dataset_id: str
    value_field: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _identifier(self.dataset_id, name="dataset_id"))
        object.__setattr__(self, "value_field", _identifier(self.value_field, name="value_field"))
        if self.value_field in _RESERVED_PUBLICATION_NAMES:
            raise ValueError(
                f"value_field must not use a framework-reserved name: {self.value_field!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordOutput:
    """A caller's selection of one diagnostic table to publish as its own dataset."""

    dataset_id: str
    table_id: str
    semantic_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _identifier(self.dataset_id, name="dataset_id"))
        object.__setattr__(self, "table_id", _identifier(self.table_id, name="table_id"))
        object.__setattr__(
            self,
            "semantic_fields",
            _unique_identifiers(self.semantic_fields, name="semantic_fields"),
        )


_RESERVED_PUBLICATION_NAMES = frozenset(
    {
        "observed_at",
        "producer",
        "stage",
        "event_time",
        "sequence",
        "source_refs",
        "source_references",
        "lineage",
        "version",
        "state_ref",
        "state_reference",
    }
)
"""Reserved because the framework stamps these identity/provenance facts on every publication."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Publication:
    """A caller's complete, atomic output selection for one completed run.

    ``allocation=None`` is explicit when no allocation is selected; ``records=()`` is explicit
    when no diagnostic record is selected. At least one of the two must be selected — an empty
    Publication is a typed refusal, not a silent no-op. Allocation and every record publish
    together in one atomic transaction.
    """

    allocation: AllocationOutput | None
    records: tuple[RecordOutput, ...]

    def __post_init__(self) -> None:
        if self.allocation is not None and not isinstance(self.allocation, AllocationOutput):
            raise TypeError("allocation must be an AllocationOutput or None")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, RecordOutput) for record in self.records
        ):
            raise TypeError("records must be a tuple of RecordOutput")
        if self.allocation is None and not self.records:
            raise ValueError("Publication must select at least one output")
        dataset_ids = tuple(record.dataset_id for record in self.records)
        if len(set(dataset_ids)) != len(dataset_ids):
            raise ValueError("records must not repeat a dataset_id")
        for record in self.records:
            reserved = sorted(set(record.semantic_fields) & _RESERVED_PUBLICATION_NAMES)
            if reserved:
                raise ValueError(
                    f"record {record.table_id!r} semantic_fields must not use "
                    f"framework-reserved names: {reserved}"
                )
