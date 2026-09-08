"""Closed declarations that establish operation ownership for a run.

**A run is configuration; a strategy is what it tries** (record `139`, design
`docs/design/the-panel-the-surface-and-the-run.md` §4). A `RunDefinition` names its universe,
period, venue, execution dataset and fill, initial account and the strategies it runs -- by
id, because it is a registered document, and the workspace is what resolves an id. Preflight
freezes the run layer once into a `FrozenRun` and each strategy into a `FrozenStrategy`; the
run layer's identity is shared by every strategy and each strategy's identity is its own.

Before `139` both types held one `strategy` field, so a run was one strategy at the level of a
dataclass field and a comparison across factor models was n runs with n copies of one period.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.dataclasses import dataclass as pydantic_dataclass

from vqapr.account.account import AccountMode
from vqapr.data.requirements import DataRequirement
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.identifiers import AgendaId, ModelStateRef
from vqapr.domain.values import ModelMemory, normalize_memory, require_tz_aware
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run_state import prepare_model_state

FINGERPRINT_PREFIX = 8
"""How much of a component fingerprint names a strategy record's directory: `<id>@<fp8>`.

Eight hex characters is 32 bits, and a strategy is edited tens of times, not billions. The full
fingerprint is inside `strategy.json`; the directory name only has to tell tweaks apart.
"""


def _identity(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _model_state_ref(memory: ModelMemory, payload: bytes) -> ModelStateRef:
    return prepare_model_state(memory, payload).ref


def _require_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty identifier")
    return value


def _require_timezone(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timezone must be a non-empty IANA timezone name")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"unknown IANA timezone: {value!r}") from error


def _require_period(start: datetime | None, end: datetime | None, verb: str) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"start and end must be {verb} together")
    if start is not None and end is not None:
        require_tz_aware(start, name="start")
        require_tz_aware(end, name="end")
        if start.astimezone(UTC) > end.astimezone(UTC):
            raise ValueError("start must not be after end")


def _require_account(
    snapshot: AccountSnapshot | None, mode: AccountMode | None, verb: str
) -> AccountSnapshot | None:
    if (snapshot is None) != (mode is None):
        raise ValueError(
            f"initial_account_snapshot and initial_account_mode must be {verb} together"
        )
    if snapshot is None:
        return None
    if not isinstance(snapshot, AccountSnapshot):
        raise TypeError("initial_account_snapshot must be an AccountSnapshot or None")
    if not isinstance(mode, AccountMode):
        raise TypeError("initial_account_mode must be an AccountMode or None")
    return AccountSnapshot(snapshot.version, snapshot.cash, snapshot.positions)


def _require_instruments(instruments: object) -> frozenset[str]:
    if not isinstance(instruments, tuple) or not instruments:
        raise ValueError("instruments must be a non-empty tuple")
    if any(not isinstance(value, str) or not value for value in instruments):
        raise ValueError("instruments must contain non-empty strings")
    unique = frozenset(instruments)
    if len(unique) != len(instruments):
        raise ValueError("instruments must be unique")
    return unique


def _require_requirements(name: str, requirements: object) -> None:
    if not isinstance(requirements, tuple) or not all(
        isinstance(requirement, DataRequirement) for requirement in requirements
    ):
        raise TypeError(f"{name} must be a tuple of DataRequirement values")


def _encoded_requirements(requirements: tuple[DataRequirement, ...]) -> list[tuple[str, str, str]]:
    return [
        (requirement.dataset_id, requirement.field_id, repr(requirement.lookback))
        for requirement in requirements
    ]


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    """The single constraint declaration shared by run consumers."""

    constraints: tuple[ComponentRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.constraints, tuple):
            raise TypeError("constraints must be a tuple of ComponentRef values")
        for constraint in self.constraints:
            if not isinstance(constraint, ComponentRef):
                raise TypeError("constraints must contain ComponentRef values")
            if constraint.kind is not ComponentKind.CONSTRAINT:
                raise ValueError("constraints must identify CONSTRAINT components")
        if len({constraint.component_id for constraint in self.constraints}) != len(
            self.constraints
        ):
            raise ValueError("constraints must not contain duplicate component references")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Strategy component and its independently owned callback agenda."""

    component: ComponentRef
    agenda_id: AgendaId

    def __post_init__(self) -> None:
        if not isinstance(self.component, ComponentRef):
            raise TypeError("component must be a ComponentRef")
        if self.component.kind is not ComponentKind.STRATEGY_MODEL:
            raise ValueError("component must identify a STRATEGY_MODEL")
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")


# ---------------------------------------------------------------------------------------------
# The run family is one shape (one-shape campaign Step 5, record 160). `RunDefinition` and its
# two entry types are what `workspace.yaml` stores under `runs:`, what a declaration registers
# and what preflight freezes -- the same object, so there is no `RunDocument.to_domain()` to
# keep in step with a `RunDefinition.__post_init__`. pydantic owns the shape (key sets, scalar
# types, enums, dates); the rules that are this package's -- one kind of model per run, ids
# named once, a venue declared whole, a period declared whole -- are validators on the model.
# The YAML spelling (strategies keyed by id, an `execution` block, one `initial_account` block) is
# accepted by a before-validator and emitted by the serializer, so the stored bytes did not move.
# ---------------------------------------------------------------------------------------------

_ENTRY_CONFIG = ConfigDict(extra="forbid", strict=False)


def _no_repeats(values: Sequence[str], what: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{what} must not repeat a component id")


@pydantic_dataclass(frozen=True, config=_ENTRY_CONFIG)
class StrategyEntry:
    """One strategy a run tries: the component, the constraints it runs under, its opening memory.

    Ids, not refs: the entry is part of a registered document, and the component it names is
    looked up by preflight, which also binds it to the run's own sessions (record `148`).
    A pydantic dataclass rather than a `BaseModel` so it keeps its positional constructor --
    `StrategyEntry("ou-k0", ("no-short",))` is how every showcase and test spells it.
    """

    component_id: Annotated[str, Field(min_length=1)]
    constraints: tuple[Annotated[str, Field(min_length=1)], ...] = ()
    initial_model_memory: Any = None

    @field_validator("constraints")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _no_repeats(value, "constraints")
        return value

    @field_validator("initial_model_memory")
    @classmethod
    def _memory(cls, value: object) -> ModelMemory:
        return normalize_memory(value)


_OUTPUT_OWNED_FIELDS = frozenset({"available_at", "instrument"})
"""Columns of a datamodel's output the package writes itself; a value field may not be one."""


def _require_value_fields(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ValueError("value_fields must name at least one output field")
    if any(
        not isinstance(name, str) or not name or any(character.isspace() for character in name)
        for name in value
    ):
        raise TypeError("value_fields must be non-empty strings without whitespace")
    if len(set(value)) != len(value):
        raise ValueError("value_fields must be unique")
    owned = sorted(set(value) & _OUTPUT_OWNED_FIELDS)
    if owned:
        raise ValueError(f"value_fields are package-owned: {owned}")
    return value


@pydantic_dataclass(frozen=True, config=_ENTRY_CONFIG)
class DataModelEntry:
    """One datamodel a run computes: the component, the dataset it writes, its opening memory.

    The output's shape is declared here and not by the model (architecture 4.4): the model
    computes rows, and what dataset those rows become -- its id and its value fields -- is
    configuration of the run that produces it (record `148`).
    """

    component_id: Annotated[str, Field(min_length=1)]
    dataset_id: Annotated[str, Field(min_length=1)]
    value_fields: tuple[str, ...]
    initial_model_memory: Any = None

    @field_validator("value_fields")
    @classmethod
    def _fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_value_fields(tuple(value))

    @field_validator("initial_model_memory")
    @classmethod
    def _memory(cls, value: object) -> ModelMemory:
        return normalize_memory(value)


class _InitialAccount(BaseModel):
    """`runs.<id>.initial_account` on disk: the YAML spelling of two `RunDefinition` fields.

    Not a domain type -- the domain is an `AccountSnapshot` and an `AccountMode` -- and not a
    document/domain pair either: it is the one block whose stored shape differs from the two
    fields it carries, so the codec for it is written once, here, as the model that reads and
    writes that block. Written and read by member NAME (`LONG_ONLY`), which is what the template
    shows; the enum's value is the lower-case spelling.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)

    cash: Decimal
    mode: AccountMode
    positions: dict[str, Decimal] = {}
    version: int = 0

    @field_validator("mode", mode="before")
    @classmethod
    def _by_name_as_written(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return AccountMode[value.upper()]
            except KeyError:
                return value
        return value

    @field_serializer("mode")
    def _name(self, mode: AccountMode) -> str:
        return mode.name

    @field_serializer("cash")
    def _cash(self, cash: Decimal) -> str:
        return str(cash)

    @field_serializer("positions")
    def _positions(self, positions: dict[str, Decimal]) -> dict[str, str]:
        return {name: str(quantity) for name, quantity in sorted(positions.items())}


class RunFill(BaseModel):
    """`runs.<id>.execution.fill`: on which session instant, at which price, a decision fills.

    The run's own fill convention (record `185`): `at` is the venue-local wall time of the fill,
    `selector` the scheduling rule, `trade_price` one of the execution dataset's numeric fields.
    `fold`/`offset` are the DST proof a stored declaration may carry; a declaration without them
    resolves the wall time from the zone and refuses an ambiguous one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)

    selector: Literal["same_day", "next_eligible"] = "same_day"
    at: time
    timezone: str
    trade_price: str
    fold: int | None = None
    offset: str | None = None

    @field_validator("selector", mode="before")
    @classmethod
    def _lowered(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("at")
    @classmethod
    def _wall_time(cls, value: time) -> time:
        return _naive_wall_time(value)

    @field_serializer("at")
    def _at_as_text(self, value: time) -> str:
        return value.isoformat()

    def to_convention(self) -> FillConvention:
        return FillConvention(
            FillSelector[self.selector.upper()],
            self.at,
            self.timezone,
            self.trade_price,
            self.fold,
            self.offset,
        )


class RunExecution(BaseModel):
    """`runs.<id>.execution`: the registered execution dataset and this run's fill on it."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=False)

    dataset: Annotated[str, Field(min_length=1)]
    fill: RunFill

    @property
    def convention(self) -> FillConvention:
        return self.fill.to_convention()


def _naive_wall_time(value: object) -> time:
    if not isinstance(value, time):
        raise ValueError("at must be a datetime.time")
    if value.tzinfo is not None:
        raise ValueError("at must be a timezone-naive wall time; the run declares the zone")
    return value


class RunDefinition(BaseModel):
    """A registered run: what every model in it shares, and which models it runs.

    A run holds one kind of model (record `148`): `strategies`, each with its own account and
    venue, or `datamodels`, each writing one dataset and touching no account. Everything here is
    an id or a value; the workspace resolves ids at preflight. Pairing rules are enforced here so
    a document cannot half-declare a venue or a period.

    This is also the `runs.<run_id>` entry of `workspace.yaml` and of a declaration, read and
    written through `model_validate` / `model_dump(mode="json")`. The stored spelling differs
    from the field names in four places, and the before-validator and serializer below are the
    one place that difference is written: `strategies`/`datamodels` are keyed by component id on
    disk and are tuples of entries here; `execution` on disk is a `RunExecution`; one
    `initial_account` block is a snapshot and a mode; and `run_id` is the key the entry sits
    under, not a field of it.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=False, arbitrary_types_allowed=True
    )

    run_id: Annotated[str, Field(min_length=1)]
    strategies: tuple[StrategyEntry, ...] = ()
    instruments: tuple[Annotated[str, Field(min_length=1)], ...]
    datamodels: tuple[DataModelEntry, ...] = ()
    """The datamodels a run computes, when it is a datamodel run. Never beside `strategies`."""
    timezone: str
    """The venue zone every wall time below is expressed in. Required: a run without one is not
    run-ready, and the dataclass's `""` default only deferred that refusal to the zone check."""
    at: time | None = None
    """When, on each session, every model is called. A strategy decides for itself whether to
    act; the book is valued at the instant the venue fills, and monitored right after each
    commit, so this is the one wall time a run declares (record `148`)."""
    sessions_from: str | None = None
    """The dataset whose distinct `available_at` days are the run's sessions."""
    sessions: tuple[date, ...] = ()
    """Or the sessions listed literally. Exactly one of the two is declared."""
    exchange: str | None = None
    execution: RunExecution | None = None
    """Which registered execution dataset the run fills against, and how: the session instant
    and the price (record `185`). The table is registered once; the price is this run's."""
    start: datetime | None = None
    end: datetime | None = None
    initial_account_snapshot: AccountSnapshot | None = None
    initial_account_mode: AccountMode | None = None

    # ---- the stored spelling in, and out ----------------------------------------------------

    @model_validator(mode="before")
    @classmethod
    def _from_the_stored_spelling(cls, raw: object) -> object:
        """Accept the `runs.<id>` block as `workspace.yaml` and a declaration write it."""
        if not isinstance(raw, Mapping):
            return raw
        body = dict(raw)
        strategies = body.get("strategies")
        if isinstance(strategies, Mapping):
            body["strategies"] = tuple(
                StrategyEntry(component_id=name, **(entry or {}))
                if isinstance(entry, Mapping) or entry is None
                else entry
                for name, entry in strategies.items()
            )
        datamodels = body.get("datamodels")
        if isinstance(datamodels, Mapping):
            body["datamodels"] = tuple(
                DataModelEntry(component_id=name, **entry) if isinstance(entry, Mapping) else entry
                for name, entry in datamodels.items()
            )
        if "execution_table" in body or "execution_input_id" in body:
            raise ValueError(
                "execution_table is retired (record 185): register the venue table as a dataset "
                "with an `execution:` role and declare `execution: {dataset, fill}` on the run"
            )
        if "initial_account" in body:
            account = body.pop("initial_account")
            if account is not None:
                declared = (
                    account
                    if isinstance(account, _InitialAccount)
                    else _InitialAccount.model_validate(account)
                )
                body["initial_account_snapshot"] = AccountSnapshot(
                    version=declared.version, cash=declared.cash, positions=declared.positions
                )
                body["initial_account_mode"] = declared.mode
        for name in ("strategies", "datamodels", "sessions", "instruments"):
            if name in body and body[name] is None:
                body[name] = ()
        return body

    @model_serializer(mode="plain")
    def _to_the_stored_spelling(self) -> dict[str, Any]:
        """Emit the `runs.<id>` block exactly as it has been written since record `148`.

        Built from the fields rather than from pydantic's own pass, because the snapshot's
        `positions` is a `MappingProxyType` pydantic cannot serialize and the block does not
        carry the snapshot as such anyway; `run_id` is the key the block sits under.
        """
        ordered: dict[str, Any] = {
            "instruments": list(self.instruments),
            "start": None if self.start is None else self.start.isoformat(),
            "end": None if self.end is None else self.end.isoformat(),
            "timezone": self.timezone,
            "at": None if self.at is None else self.at.isoformat(),
            "exchange": self.exchange,
            "execution": None if self.execution is None else self.execution.model_dump(mode="json"),
        }
        if self.initial_account_snapshot is not None and self.initial_account_mode is not None:
            ordered["initial_account"] = _InitialAccount(
                cash=self.initial_account_snapshot.cash,
                mode=self.initial_account_mode,
                positions=dict(self.initial_account_snapshot.positions),
                version=self.initial_account_snapshot.version,
            ).model_dump(mode="json")
        if self.strategies:
            ordered["strategies"] = {
                entry.component_id: _entry_body(entry, ("constraints", "initial_model_memory"))
                for entry in self.strategies
            }
        if self.datamodels:
            ordered["datamodels"] = {
                entry.component_id: _entry_body(
                    entry, ("dataset_id", "value_fields", "initial_model_memory")
                )
                for entry in self.datamodels
            }
        if self.sessions_from is not None:
            ordered["sessions_from"] = self.sessions_from
        if self.sessions:
            ordered["sessions"] = [day.isoformat() for day in self.sessions]
        return ordered

    # ---- this package's rules ----------------------------------------------------------------

    @field_validator("at")
    @classmethod
    def _wall_time(cls, value: time | None) -> time | None:
        return None if value is None else _naive_wall_time(value)

    @field_validator("sessions", mode="before")
    @classmethod
    def _declared_sessions(cls, value: object) -> object:
        # `None` on disk is "not declared", and so is the domain's `()` default. An explicit
        # empty LIST is a declaration of nothing -- a declaration writes lists -- which the
        # document refused by name and this keeps refusing by name.
        if value is None:
            return ()
        if isinstance(value, list) and not value:
            raise ValueError("sessions must list at least one date")
        return value

    @field_validator("sessions")
    @classmethod
    def _dates_only(cls, value: tuple[date, ...]) -> tuple[date, ...]:
        for day in value:
            if isinstance(day, datetime) or not isinstance(day, date):
                raise ValueError("sessions must be a tuple of dates")
        return value

    @field_validator("start", "end")
    @classmethod
    def _one_instant(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError(
                "must be timezone-aware: include a UTC offset, a naive datetime is not one instant"
            )
        return value

    @model_validator(mode="after")
    def _whole_declaration(self) -> RunDefinition:
        if bool(self.strategies) == bool(self.datamodels):
            raise ValueError(
                "must name at least one model under exactly one of `strategies:` or "
                "`datamodels:` -- a run names at least one strategy or at least one datamodel, "
                "not both (record 148: a run holds one kind)"
            )
        ids = [entry.component_id for entry in (*self.strategies, *self.datamodels)]
        if len(set(ids)) != len(ids):
            raise ValueError("a run names each model at most once")
        outputs = [entry.dataset_id for entry in self.datamodels]
        if len(set(outputs)) != len(outputs):
            raise ValueError("a run writes each output dataset at most once")
        if self.datamodels:
            declared = [
                key
                for key, value in (
                    ("exchange", self.exchange),
                    ("execution", self.execution),
                    ("initial_account", self.initial_account_snapshot),
                    ("initial_account", self.initial_account_mode),
                )
                if value is not None
            ]
            if declared:
                raise ValueError(
                    f"a datamodel run declares no {', '.join(dict.fromkeys(declared))}: a "
                    "datamodel run declares no exchange, execution or initial_account, "
                    "because a datamodel sees no account and passes through no venue"
                )
        _require_timezone(self.timezone)
        if self.at is None:
            raise ValueError("at must be declared")
        if (self.sessions_from is None) == (not self.sessions):
            raise ValueError("declare exactly one of sessions_from or sessions")
        if self.sessions_from is not None and not self.sessions_from:
            raise ValueError("sessions_from must be a non-empty identifier")
        if self.exchange is not None and not self.exchange:
            raise ValueError("exchange must be a non-empty identifier")
        if (self.exchange is None) != (self.execution is None):
            raise ValueError("exchange and execution must be declared together")
        _require_period(self.start, self.end, "declared")
        _require_account(self.initial_account_snapshot, self.initial_account_mode, "declared")
        _require_instruments(self.instruments)
        return self

    # ---- what the flow asks a run ------------------------------------------------------------

    def spoken(self) -> list[str]:
        """The point-in-time meaning of this declaration, in one sentence (`docs/issues/027`)."""
        when = "" if self.at is None else f" at {self.at.isoformat()} {self.timezone}"
        sentences: list[str] = []
        if self.execution is not None:
            fill = self.execution.fill
            sentences.append(
                f"run {self.run_id!r} fills against dataset {self.execution.dataset!r}: "
                f"{fill.selector} at {fill.at.isoformat()} {fill.timezone}, at its "
                f"{fill.trade_price!r} price"
            )
        sentences.append(
            f"run {self.run_id!r}: every model is called{when} on each session and sees only "
            "rows knowable before that instant; the book fills later, at the execution dataset's "
            "own instant"
        )
        return sentences

    def replace(self, **changes: Any) -> RunDefinition:
        """A copy with some fields changed, **validated again**.

        pydantic's `model_copy(update=...)` does not re-run validators -- a copy with a naive
        `start` or a half-declared account would come back looking valid. `dataclasses.replace`
        re-ran `__post_init__`, and every caller that reached for it relied on that; this keeps
        the promise by rebuilding the definition from its fields through `model_validate`.
        """
        fields = {name: getattr(self, name) for name in type(self).model_fields}
        return type(self).model_validate({**fields, **changes})

    @property
    def agenda_id(self) -> str:
        """The id of the one agenda preflight derives: every session, at `at`."""
        return f"{self.run_id}.sessions"

    @property
    def kind(self) -> str:
        """`"strategy"` or `"datamodel"`: which kind of model this run holds."""
        return "datamodel" if self.datamodels else "strategy"

    @property
    def members(self) -> tuple[StrategyEntry | DataModelEntry, ...]:
        """The models the run names, whichever kind it holds."""
        return (*self.strategies, *self.datamodels)

    def strategy(self, component_id: str) -> StrategyEntry:
        for entry in self.strategies:
            if entry.component_id == component_id:
                return entry
        raise KeyError(
            f"run {self.run_id!r} does not name strategy {component_id!r}; it names "
            f"{', '.join(entry.component_id for entry in self.members)}"
        )

    def datamodel(self, component_id: str) -> DataModelEntry:
        for entry in self.datamodels:
            if entry.component_id == component_id:
                return entry
        raise KeyError(
            f"run {self.run_id!r} does not name datamodel {component_id!r}; it names "
            f"{', '.join(entry.component_id for entry in self.members)}"
        )

    def member(self, component_id: str) -> StrategyEntry | DataModelEntry:
        """The named model of whichever kind the run holds."""
        return self.datamodel(component_id) if self.datamodels else self.strategy(component_id)


def _entry_body(entry: object, names: Sequence[str]) -> dict[str, Any]:
    """An entry's declared fields as its stored block: only what was declared, in the stored
    order, `constraints` and `initial_model_memory` omitted when empty (as the document always
    wrote them)."""
    body: dict[str, Any] = {}
    for name in names:
        value = getattr(entry, name)
        if name == "constraints" and not value:
            continue
        if name == "initial_model_memory" and value is None:
            continue
        body[name] = list(value) if isinstance(value, tuple) else value
    return body
