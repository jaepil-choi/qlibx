"""Closed declarations that establish operation ownership for a run.

**A run is configuration; a strategy is what it tries** (record `139`, design
`docs/design/the-panel-the-surface-and-the-run.md` §4). A `RunDefinition` names its universe,
period, venue, execution input, initial account declaration and the strategies it runs -- by
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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import MappingProxyType
from typing import Annotated, Any
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
from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import AgendaId
from vqapr.domain.memory import ModelMemory, normalize_memory
from vqapr.domain.references import ModelStateRef
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import ExecutionInputRegistration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.model_state import prepare_model_state
from vqapr.runtime.agendas import OperationOccurrence, OperationRole

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
    agenda_role: OperationRole

    def __post_init__(self) -> None:
        if not isinstance(self.component, ComponentRef):
            raise TypeError("component must be a ComponentRef")
        if self.component.kind is not ComponentKind.STRATEGY_MODEL:
            raise ValueError("component must identify a STRATEGY_MODEL")
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.agenda_role, OperationRole):
            raise TypeError("agenda_role must be an OperationRole")
        if self.agenda_role is not OperationRole.STRATEGY_CALLBACK:
            raise ValueError("strategy agenda_role must be STRATEGY_CALLBACK")


# ---------------------------------------------------------------------------------------------
# The run family is one shape (one-shape campaign Step 5, record 160). `RunDefinition` and its
# two entry types are what `workspace.yaml` stores under `runs:`, what a declaration registers
# and what preflight freezes -- the same object, so there is no `RunDocument.to_domain()` to
# keep in step with a `RunDefinition.__post_init__`. pydantic owns the shape (key sets, scalar
# types, enums, dates); the rules that are this package's -- one kind of model per run, ids
# named once, a venue declared whole, a period declared whole -- are validators on the model.
# The YAML spelling (strategies keyed by id, `execution_input`, one `initial_account` block) is
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
    disk and are tuples of entries here; `execution_input` on disk is `execution_input_id`; one
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
    execution_input_id: str | None = None
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
        if "execution_input" in body:
            if "execution_input_id" in body:
                raise ValueError("declare execution_input once, not also as execution_input_id")
            body["execution_input_id"] = body.pop("execution_input")
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
            "execution_input": self.execution_input_id,
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
                    ("execution_input", self.execution_input_id),
                    ("initial_account", self.initial_account_snapshot),
                    ("initial_account", self.initial_account_mode),
                )
                if value is not None
            ]
            if declared:
                raise ValueError(
                    f"a datamodel run declares no {', '.join(dict.fromkeys(declared))}: a "
                    "datamodel run declares no exchange, execution_input or initial_account, "
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
        if self.execution_input_id is not None and not self.execution_input_id:
            raise ValueError("execution_input_id must be a non-empty identifier")
        if (self.exchange is None) != (self.execution_input_id is None):
            raise ValueError("exchange and execution_input_id must be declared together")
        _require_period(self.start, self.end, "declared")
        _require_account(self.initial_account_snapshot, self.initial_account_mode, "declared")
        _require_instruments(self.instruments)
        return self

    # ---- what the flow asks a run ------------------------------------------------------------

    def spoken(self) -> list[str]:
        """The point-in-time meaning of this declaration, in one sentence (`docs/issues/027`)."""
        when = "" if self.at is None else f" at {self.at.isoformat()} {self.timezone}"
        return [
            f"run {self.run_id!r}: every model is called{when} on each session and sees only "
            "rows knowable before that instant; the book fills later, at the execution input's "
            "own instant"
        ]

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


@dataclass(frozen=True, slots=True)
class FrozenAgenda:
    """A resolved owner agenda identity and its inclusive run slice."""

    agenda_id: AgendaId
    agenda_role: OperationRole
    occurrences: tuple[OperationOccurrence, ...]
    timezone: str = ""
    content_identity: str = ""
    provenance_identity: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.agenda_role, OperationRole):
            raise TypeError("agenda_role must be an OperationRole")
        if not isinstance(self.occurrences, tuple):
            raise TypeError("occurrences must be a tuple of OperationOccurrence values")
        if not isinstance(self.timezone, str):
            raise TypeError("timezone must be an IANA timezone name")
        if not self.timezone and (self.content_identity or self.provenance_identity):
            raise ValueError("agenda identities require a timezone")
        for name, value in (
            ("content_identity", self.content_identity),
            ("provenance_identity", self.provenance_identity),
        ):
            if not isinstance(value, str) or (value and len(value) != 64):
                raise TypeError(f"{name} must be a SHA-256 identity")
        if bool(self.content_identity) != bool(self.provenance_identity):
            raise ValueError("agenda identities must be supplied together")
        for occurrence in self.occurrences:
            if not isinstance(occurrence, OperationOccurrence):
                raise TypeError("occurrences must contain OperationOccurrence values")
            if occurrence.role is not self.agenda_role:
                raise ValueError("occurrence role must match agenda_role")

    def encoded(self) -> tuple[str, str, list[str]]:
        """What a model's identity folds of its agenda: the sessions' CONTENT, not their name.

        The role, the zone and each occurrence's local instant. Not the agenda id, its
        provenance or the occurrence ids: since record `148` the agenda is derived from the run
        (`<run_id>.sessions`, occurrences `<run_id>.sessions-<date>`), so folding those would
        make the same strategy on the same sessions a different identity under every run id --
        which is the run's identity, not the strategy's (owner ruling, 2026-09-03).
        """
        return (
            self.agenda_role.value,
            self.timezone,
            [occurrence.local_instant.identity() for occurrence in self.occurrences],
        )


def merged_occurrences(*agendas: FrozenAgenda | None) -> tuple[OperationOccurrence, ...]:
    """The deterministic static dispatch order of several agendas: one sorted merge."""
    return tuple(
        sorted(
            (
                occurrence
                for agenda in agendas
                if agenda is not None
                for occurrence in agenda.occurrences
            ),
            key=OperationOccurrence.sort_key,
        )
    )


@dataclass(frozen=True, slots=True)
class FrozenStrategy:
    """One strategy's layer of a frozen run: what is its own and not the run's.

    Its identity folds the component fingerprint, its constraints, its agenda slice, its opening
    memory and what it reads. Two strategies in one run differ here and nowhere else.
    """

    config: StrategyConfig
    constraints: ConstraintSet
    agenda: FrozenAgenda
    requirements: tuple[DataRequirement, ...] = ()
    constraint_requirements: tuple[DataRequirement, ...] = ()
    initial_model_memory: ModelMemory = None
    initial_payload: bytes = b""
    initial_model_state_ref: ModelStateRef = field(init=False)
    _identity: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.config, StrategyConfig):
            raise TypeError("config must be a StrategyConfig")
        if not isinstance(self.constraints, ConstraintSet):
            raise TypeError("constraints must be a ConstraintSet")
        if not isinstance(self.agenda, FrozenAgenda):
            raise TypeError("agenda must be a FrozenAgenda")
        if self.agenda.agenda_id != self.config.agenda_id:
            raise ValueError("agenda must match the strategy config's agenda_id")
        if self.agenda.agenda_role is not self.config.agenda_role:
            raise ValueError("agenda must match the strategy config's agenda_role")
        _require_requirements("requirements", self.requirements)
        _require_requirements("constraint_requirements", self.constraint_requirements)
        memory = normalize_memory(self.initial_model_memory)
        object.__setattr__(self, "initial_model_memory", memory)
        if not isinstance(self.initial_payload, bytes):
            raise TypeError("initial_payload must be bytes")
        object.__setattr__(self, "initial_payload", bytes(self.initial_payload))
        object.__setattr__(
            self, "initial_model_state_ref", _model_state_ref(memory, self.initial_payload)
        )

    @property
    def component_id(self) -> str:
        return str(self.config.component.component_id)

    @property
    def record_ref(self) -> str:
        """The name of this strategy's record directory: `<component_id>@<fingerprint[:8]>`.

        Content-addressed by the REGISTERED fingerprint, which folds the file bytes, the object
        name and the config: a condition tweaked in `config` makes a new directory beside the
        old one, which is what makes "how many times was this strategy tweaked" a directory count
        (architecture §17.4).
        """
        return f"{self.component_id}@{self.config.component.fingerprint[:FINGERPRINT_PREFIX]}"

    @property
    def identity(self) -> str:
        if not self._identity:
            object.__setattr__(
                self,
                "_identity",
                _identity(
                    {
                        "strategy": (
                            self.component_id,
                            self.config.component.fingerprint,
                        ),
                        "constraints": [
                            (constraint.component_id, constraint.fingerprint)
                            for constraint in self.constraints.constraints
                        ],
                        "agenda": self.agenda.encoded(),
                        "initial_model_memory": self.initial_model_memory,
                        "initial_model_state_ref": self.initial_model_state_ref.digest,
                        "initial_payload": self.initial_payload.hex(),
                        "requirements": _encoded_requirements(self.requirements),
                        "constraint_requirements": _encoded_requirements(
                            self.constraint_requirements
                        ),
                    }
                ),
            )
        return self._identity


@dataclass(frozen=True, slots=True)
class FrozenDataModel:
    """One datamodel's layer of a frozen run: the component, its agenda slice, and its output.

    The datamodel counterpart of `FrozenStrategy`, minus what a datamodel has none of: no
    constraints, no account, no payload. Its identity folds the component fingerprint, the
    agenda slice, the output declaration, its opening memory and what it reads.
    """

    component: ComponentRef
    agenda: FrozenAgenda
    dataset_id: str
    value_fields: tuple[str, ...]
    requirements: tuple[DataRequirement, ...] = ()
    initial_model_memory: ModelMemory = None
    _identity: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.component, ComponentRef):
            raise TypeError("component must be a ComponentRef")
        if self.component.kind is not ComponentKind.DATA_MODEL:
            raise ValueError("component must identify a DATA_MODEL")
        if not isinstance(self.agenda, FrozenAgenda):
            raise TypeError("agenda must be a FrozenAgenda")
        if self.agenda.agenda_role is not OperationRole.STRATEGY_CALLBACK:
            raise ValueError("a datamodel is called on the run's sessions, the callback role")
        _require_id(self.dataset_id, "dataset_id")
        _require_value_fields(self.value_fields)
        _require_requirements("requirements", self.requirements)
        object.__setattr__(
            self, "initial_model_memory", normalize_memory(self.initial_model_memory)
        )

    @property
    def component_id(self) -> str:
        return str(self.component.component_id)

    @property
    def record_ref(self) -> str:
        """The name of this datamodel's record directory: `<component_id>@<fingerprint[:8]>`."""
        return f"{self.component_id}@{self.component.fingerprint[:FINGERPRINT_PREFIX]}"

    @property
    def identity(self) -> str:
        if not self._identity:
            object.__setattr__(
                self,
                "_identity",
                _identity(
                    {
                        "datamodel": (self.component_id, self.component.fingerprint),
                        "agenda": self.agenda.encoded(),
                        "output": (self.dataset_id, list(self.value_fields)),
                        "initial_model_memory": self.initial_model_memory,
                        "requirements": _encoded_requirements(self.requirements),
                    }
                ),
            )
        return self._identity


@dataclass(frozen=True, slots=True)
class FrozenRun:
    """Frozen owner declarations retained by a future preflight result.

    The run layer -- what every strategy shares -- plus the frozen strategies. `identity` is the
    run layer's alone, so adding a strategy to a run does not rename the rows the others wrote;
    `requirements`, `datasets` and `sources` are the union every strategy and constraint reads,
    which is the panel set (design §4.1).
    """

    run_id: str
    strategies: tuple[FrozenStrategy, ...]
    datamodels: tuple[FrozenDataModel, ...] = field(default=(), kw_only=True)
    exchange: ComponentRef | None = None
    execution_input: ExecutionInputRegistration | None = None
    start: datetime | None = None
    end: datetime | None = None
    initial_account_snapshot: AccountSnapshot | None = None
    initial_account_mode: AccountMode | None = None
    instruments: tuple[str, ...] = ()
    instrument_set: frozenset[str] = field(init=False, repr=False, compare=False)
    requirements: tuple[DataRequirement, ...] = ()
    datasets: tuple[DatasetRegistration, ...] = ()
    sources: tuple[SourceSpec, ...] = ()
    _identity: str = field(default="", init=False, repr=False, compare=False)
    """Memo for `identity`, which every frozen field already determines.

    A run reads this about sixteen times per callback, and deriving it walks every occurrence of
    every agenda. Recomputing therefore cost O(occurrences) per callback -- quadratic in run
    length -- to produce a string that cannot change once `__post_init__` returns.
    """

    def __post_init__(self) -> None:
        _require_id(self.run_id, "run_id")
        if not isinstance(self.strategies, tuple) or any(
            not isinstance(layer, FrozenStrategy) for layer in self.strategies
        ):
            raise TypeError("strategies must contain FrozenStrategy values")
        if not isinstance(self.datamodels, tuple) or any(
            not isinstance(layer, FrozenDataModel) for layer in self.datamodels
        ):
            raise TypeError("datamodels must contain FrozenDataModel values")
        if bool(self.strategies) == bool(self.datamodels):
            raise ValueError("a frozen run holds strategies or datamodels, at least one, not both")
        ids = [layer.component_id for layer in (*self.strategies, *self.datamodels)]
        if len(set(ids)) != len(ids):
            raise ValueError("a frozen run holds each model at most once")
        if self.datamodels and (
            self.exchange is not None
            or self.execution_input is not None
            or self.initial_account_snapshot is not None
        ):
            raise ValueError("a frozen datamodel run holds no venue, execution input or account")
        if self.exchange is not None:
            if not isinstance(self.exchange, ComponentRef):
                raise TypeError("exchange must be a ComponentRef or None")
            if self.exchange.kind is not ComponentKind.EXCHANGE:
                raise ValueError("exchange must identify an EXCHANGE component")
        if (self.exchange is None) != (self.execution_input is None):
            raise ValueError("exchange and execution_input must be frozen together")
        if self.execution_input is not None and not isinstance(
            self.execution_input, ExecutionInputRegistration
        ):
            raise TypeError("execution_input must be an ExecutionInputRegistration or None")
        _require_period(self.start, self.end, "frozen")
        object.__setattr__(
            self,
            "initial_account_snapshot",
            _require_account(self.initial_account_snapshot, self.initial_account_mode, "frozen"),
        )
        # The uniqueness check needs this set anyway; keeping it turns per-callback universe
        # membership from a linear tuple scan into a hash lookup.
        object.__setattr__(self, "instrument_set", _require_instruments(self.instruments))
        _require_requirements("requirements", self.requirements)
        if not isinstance(self.datasets, tuple) or not all(
            isinstance(dataset, DatasetRegistration) for dataset in self.datasets
        ):
            raise TypeError("datasets must be a tuple of DatasetRegistration values")
        dataset_ids = [dataset.dataset_id for dataset in self.datasets]
        if len(set(dataset_ids)) != len(dataset_ids) or dataset_ids != sorted(dataset_ids):
            raise ValueError("datasets must be unique and ordered by dataset_id")
        object.__setattr__(
            self,
            "datasets",
            tuple(
                # Detaching copies the MEASUREMENTS too, not just the declaration. `aggregated`
                # decides which query the read path composes, so a copy that dropped it would
                # read a grouped registration row-wise -- the same rows, silently ungrouped, with
                # no error anywhere. `span` and `field_types` are carried for the same reason
                # this copy exists at all: a frozen run must describe what was registered.
                # By keyword: `grain` joined the registration between `fields` and `span`
                # (record `137`), and a positional rebuild put the span into it.
                DatasetRegistration(
                    dataset_id=dataset.dataset_id,
                    source=dataset.source,
                    instrument_field=dataset.instrument_field,
                    available_at=dataset.available_at,
                    key_fields=dataset.key_fields,
                    fields=MappingProxyType(dict(dataset.fields)),
                    grain=dataset.grain,
                    span=dataset.span,
                    field_types=None
                    if dataset.field_types is None
                    else MappingProxyType(dict(dataset.field_types)),
                    aggregated=dataset.aggregated,
                )
                for dataset in self.datasets
            ),
        )
        if not isinstance(self.sources, tuple) or not all(
            isinstance(source, SourceSpec) for source in self.sources
        ):
            raise TypeError("sources must be a tuple of SourceSpec values")
        source_ids = [source.source_id for source in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("sources must not contain duplicate source declarations")
        if source_ids != sorted(source_ids):
            raise ValueError("sources must be ordered by source_id")

    @property
    def kind(self) -> str:
        return "datamodel" if self.datamodels else "strategy"

    @property
    def members(self) -> tuple[FrozenStrategy | FrozenDataModel, ...]:
        return (*self.strategies, *self.datamodels)

    def strategy(self, component_id: str) -> FrozenStrategy:
        for layer in self.strategies:
            if layer.component_id == component_id:
                return layer
        raise KeyError(
            f"run {self.run_id!r} froze no strategy {component_id!r}; it holds "
            f"{', '.join(layer.component_id for layer in self.members)}"
        )

    def datamodel(self, component_id: str) -> FrozenDataModel:
        for layer in self.datamodels:
            if layer.component_id == component_id:
                return layer
        raise KeyError(
            f"run {self.run_id!r} froze no datamodel {component_id!r}; it holds "
            f"{', '.join(layer.component_id for layer in self.members)}"
        )

    def member(self, component_id: str) -> FrozenStrategy | FrozenDataModel:
        return self.datamodel(component_id) if self.datamodels else self.strategy(component_id)

    def dispatch_order(
        self, layer: FrozenStrategy | FrozenDataModel
    ) -> tuple[OperationOccurrence, ...]:
        """The static occurrences one model's flow dispatches: its sessions, at `at`.

        Since record `148` a run has one agenda: the book is valued at the instant the venue
        fills and monitored right after each commit, so there is nothing else to merge in.
        """
        return merged_occurrences(layer.agenda)

    @property
    def identity(self) -> str:
        """Canonical identity of the run layer: what every strategy in this run shares."""
        if not self._identity:
            object.__setattr__(self, "_identity", self._derive_identity())
        return self._identity

    def _derive_identity(self) -> str:
        return _identity(
            {
                "run_id": self.run_id,
                "exchange": (
                    (self.exchange.component_id, self.exchange.fingerprint)
                    if self.exchange is not None
                    else None
                ),
                "execution_input": (
                    {
                        "execution_input_id": self.execution_input.execution_input_id,
                        "source": (
                            self.execution_input.table.source.source_id,
                            str(self.execution_input.table.source.path),
                            self.execution_input.table.source.hive_partitioned,
                        ),
                        "table": (
                            self.execution_input.table.trade_at_field,
                            self.execution_input.table.instrument_field,
                            self.execution_input.table.is_tradable_field,
                            tuple(sorted(self.execution_input.table.price_fields.items())),
                        ),
                        "fill": self.execution_input.fill.declaration_identity,
                    }
                    if self.execution_input is not None
                    else None
                ),
                "start": self.start.astimezone(UTC).isoformat() if self.start is not None else None,
                "end": self.end.astimezone(UTC).isoformat() if self.end is not None else None,
                "initial_account": (
                    (
                        self.initial_account_mode.value,
                        self.initial_account_snapshot.version,
                        str(self.initial_account_snapshot.cash),
                        tuple(
                            (instrument, str(quantity))
                            for instrument, quantity in (
                                self.initial_account_snapshot.positions.items()
                            )
                        ),
                    )
                    if self.initial_account_snapshot is not None
                    else None
                ),
                "instruments": self.instruments,
                "requirements": _encoded_requirements(self.requirements),
                "datasets": [
                    (
                        dataset.dataset_id,
                        dataset.source,
                        dataset.instrument_field,
                        dataset.available_at,
                        dataset.key_fields,
                        tuple(sorted(dataset.fields.items())),
                    )
                    for dataset in self.datasets
                ],
                "sources": [
                    (source.source_id, str(source.path), source.hive_partitioned)
                    for source in self.sources
                ],
            }
        )

    @property
    def physical_source_guarantee(self) -> str:
        """The freeze covers declarations, not source bytes."""
        return "Configuration and declaration objects are frozen; physical source bytes are not."
