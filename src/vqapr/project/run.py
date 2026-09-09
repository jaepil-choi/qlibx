"""Closed declarations that establish operation ownership for a run.

**A run is configuration; a strategy is what it tries** (record `139`, design
`docs/design/the-panel-the-surface-and-the-run.md` §4). A `RunDefinition` names its universe,
period, venue, execution dataset and fill, initial account and the one model it runs -- by id,
because it is a registered document, and the workspace is what resolves an id. Preflight freezes
the run layer into a `FrozenRun` and its model into a `FrozenStrategy`; the run layer's identity
and the model's identity are separate.

**One model per run** (2026-09-09, `docs/design/two-clocks-and-the-wiring-table.md` §2.3). Record
`139` had made it several so that a comparison across factor models would share one frozen layer.
Determinism already gives that -- two runs declaring the same inputs freeze identically -- so the
sharing bought an optimisation and cost two things: parallelism lived inside a run rather than
across independent runs, and strategies run on different days could not be compared at all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
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
from vqapr.domain.model_state import prepare_model_state
from vqapr.domain.values import ModelMemory, normalize_memory, require_tz_aware
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.extension.component import ComponentKind, ComponentRef

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
    """One datamodel a run computes: the component, its output fields, its opening memory.

    The output's shape is declared here and not by the model (architecture 4.4): the model
    computes rows, and what fields those rows carry is configuration of the run that produces it
    (record `148`). **Which dataset they become is the run's `writes`**, not this entry's: what a
    run puts in the warehouse is a property of the run, the same for a strategy as for a
    datamodel (`docs/design/two-clocks-and-the-wiring-table.md` §2).
    """

    component_id: Annotated[str, Field(min_length=1)]
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


def _singular_block(body: dict[str, Any], singular: str, plural: str) -> object:
    """The member block under either spelling, normalised to `{component_id: fields}`.

    Stored today as `strategy: {component: id, ...}` / `datamodel: {component: id, ...}` -- one
    model, named as a block. Read yesterday's `strategies: {id: {...}}` too, so a workspace written
    before 2026-09-09 opens; `_the_one_member` refuses it if it named two.
    """
    if plural in body:
        return body.pop(plural)
    block = body.get(singular)
    if isinstance(block, Mapping) and ("component" in block or "component_id" in block):
        fields = dict(block)
        name = fields.pop("component", None) or fields.pop("component_id")
        fields.pop("component_id", None)
        return {str(name): fields}
    return block


def _the_one_member[Entry](
    declared: object,
    *,
    build: Callable[[str, dict[str, Any]], Entry],
    plural: str,
) -> Entry | None:
    """The single member a run names, from any of the spellings a document may carry it in.

    A run is one arrow of the project's dataset graph and so runs one model
    (`docs/design/two-clocks-and-the-wiring-table.md` §2.3). The stored block is still the
    `plural: {component_id: {...}}` mapping it has always been, holding exactly one entry, so a
    workspace written before this rule reads back unchanged unless it actually declared two --
    and then it is refused by name rather than half-run.
    """
    if declared is None:
        return None
    if isinstance(declared, Mapping):
        items = list(declared.items())
    elif isinstance(declared, (tuple, list)):
        items = [(getattr(entry, "component_id", ""), entry) for entry in declared]
    else:
        return declared  # type: ignore[return-value]
    if not items:
        return None
    if len(items) > 1:
        named = ", ".join(sorted(str(name) for name, _ in items))
        raise ValueError(
            f"a run names exactly one model; `{plural}:` named {len(items)} ({named}). "
            "Register one run per model -- they share nothing a run has to hold them together "
            "for, and independent runs parallelise where a run's members could not"
        )
    name, entry = items[0]
    if isinstance(entry, (StrategyEntry, DataModelEntry)):
        return entry  # type: ignore[return-value]
    if entry is None:
        return build(str(name), {})
    if not isinstance(entry, Mapping):
        raise ValueError(f"`{plural}.{name}` must be a block of fields")
    return build(str(name), dict(entry))


class RunDefinition(BaseModel):
    """A registered run: what every model in it shares, and which models it runs.

    A run runs ONE model of one kind (record `148`; `docs/design/two-clocks-and-the-wiring-table.md`
    §2.3): a `strategy`, with its own account and venue, or a `datamodel`, writing one dataset and
    touching no account. Everything here is an id or a value; the workspace resolves ids at
    preflight. Pairing rules are enforced here so a document cannot half-declare a venue or a
    period.

    **One model, because a run is one arrow of the project's dataset graph.** It held several
    until 2026-09-09. The reason given was that members must share a frozen layer to be
    comparable -- but determinism already guarantees that two runs declaring the same inputs
    freeze identically, so sharing was an optimisation and not a meaning. What it cost was real:
    parallelism lived inside a run instead of across independent runs, and two strategies run on
    different days could not be compared at all.

    This is also the `runs.<run_id>` entry of `workspace.yaml` and of a declaration, read and
    written through `model_validate` / `model_dump(mode="json")`. The stored spelling differs
    from the field names in four places, and the before-validator and serializer below are the
    one place that difference is written: `strategy`/`datamodel` are a block naming its
    `component` on disk and an entry here (the pre-2026-09-09 `strategies: {id: {...}}` mapping
    is still read); `execution` on disk is a `RunExecution`; one `initial_account` block is a
    snapshot and a mode; and `run_id` is the key the entry sits under, not a field of it.
    `writes` is spelled the same in both.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=False, arbitrary_types_allowed=True
    )

    run_id: Annotated[str, Field(min_length=1)]
    writes: Annotated[str, Field(min_length=1)]
    """The dataset this run puts in the warehouse. Required: a run is one arrow of the project's
    dataset graph, and an arrow that makes nothing is not a rule of it. A strategy publishes its
    allocation under this name; a datamodel its computed rows. The name only -- the schema is
    what the consumer declares (`DataRequirement`), and saying it twice would let it disagree."""
    strategy: StrategyEntry | None = None
    """The one strategy this run executes, when it is a strategy run. Never beside `datamodel`."""
    instruments: tuple[Annotated[str, Field(min_length=1)], ...]
    datamodel: DataModelEntry | None = None
    """The one dataset this run computes, when it is a datamodel run. Never beside `strategy`."""
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
        strategy = _singular_block(body, "strategy", "strategies")
        datamodel = _singular_block(body, "datamodel", "datamodels")
        # A datamodel block written before `writes` moved to the run carried `dataset_id`
        # inside the entry. Hoist it, so a workspace from then reads back unchanged.
        if isinstance(datamodel, Mapping):
            for name, entry in datamodel.items():
                if isinstance(entry, Mapping) and "dataset_id" in entry:
                    entry = dict(entry)
                    hoisted = entry.pop("dataset_id")
                    declared = body.get("writes")
                    if declared is not None and declared != hoisted:
                        raise ValueError(
                            f"writes {declared!r} and the datamodel's dataset_id {hoisted!r} "
                            "disagree; `dataset_id` moved to the run as `writes` -- declare it once"
                        )
                    body["writes"] = hoisted
                    # Replace this entry only. Collapsing the mapping to it would hide a second
                    # member from the one-model rule below.
                    datamodel = {**datamodel, name: entry}
                    break
        body["strategy"] = _the_one_member(
            strategy,
            build=lambda name, fields: StrategyEntry(component_id=name, **fields),
            plural="strategies",
        )
        body["datamodel"] = _the_one_member(
            datamodel,
            build=lambda name, fields: DataModelEntry(component_id=name, **fields),
            plural="datamodels",
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
        for name in ("sessions", "instruments"):
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
            "writes": self.writes,
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
        if self.strategy is not None:
            ordered["strategy"] = {
                "component": self.strategy.component_id,
                **_entry_body(self.strategy, ("constraints", "initial_model_memory")),
            }
        if self.datamodel is not None:
            ordered["datamodel"] = {
                "component": self.datamodel.component_id,
                **_entry_body(self.datamodel, ("value_fields", "initial_model_memory")),
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
        if (self.strategy is None) == (self.datamodel is None):
            raise ValueError(
                "must name one model under exactly one of `strategies:` or `datamodels:` -- a "
                "run runs one strategy or one datamodel, not both and not neither "
                "(record 148: a run holds one kind; a run is one arrow of the graph)"
            )
        if self.sessions_from is not None and self.writes == self.sessions_from:
            raise ValueError(
                f"writes {self.writes!r} is also sessions_from: a run cannot take its sessions "
                "from the dataset it is about to write"
            )
        if self.execution is not None and self.writes == self.execution.dataset:
            raise ValueError(
                f"writes {self.writes!r} is also the execution dataset: a run cannot fill "
                "against the dataset it is about to write"
            )
        if self.datamodel is not None:
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
        """The point-in-time meaning of this declaration, in one sentence
        (`docs/issues/archive/027`).
        """
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
        return "datamodel" if self.datamodel is not None else "strategy"

    @property
    def member(self) -> StrategyEntry | DataModelEntry:
        """The one model the run names, whichever kind it holds."""
        one = self.strategy if self.strategy is not None else self.datamodel
        if one is None:  # pragma: no cover -- `_whole_declaration` refuses this
            raise ValueError(f"run {self.run_id!r} names no model")
        return one


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
