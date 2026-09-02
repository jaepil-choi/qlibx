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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

from vqapr.account.account import AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.requirements import DataRequirement
from vqapr.data.sources import SourceSpec
from vqapr.domain.identifiers import AgendaId
from vqapr.domain.references import ModelStateRef
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import ExecutionInputRegistration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.model_state import prepare_model_state
from vqapr.models.memory import ModelMemory, normalize_memory
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig

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


@dataclass(frozen=True, slots=True)
class StrategyEntry:
    """One strategy a run tries: the component, the constraints it runs under, its opening memory.

    Ids, not refs: the entry is part of a registered document, and the binding to an agenda is
    the strategy's registered `strategy_config` (record `138`), which preflight looks up.
    """

    component_id: str
    constraints: tuple[str, ...] = ()
    initial_model_memory: ModelMemory = None

    def __post_init__(self) -> None:
        _require_id(self.component_id, "component_id")
        if not isinstance(self.constraints, tuple) or any(
            not isinstance(name, str) or not name for name in self.constraints
        ):
            raise TypeError("constraints must be a tuple of component ids")
        if len(set(self.constraints)) != len(self.constraints):
            raise ValueError("constraints must not repeat a component id")
        object.__setattr__(
            self, "initial_model_memory", normalize_memory(self.initial_model_memory)
        )


@dataclass(frozen=True, slots=True)
class RunDefinition:
    """A registered run: what every strategy in it shares, and which strategies it tries.

    Everything here is an id or a value; the workspace resolves ids at preflight. Pairing rules
    are enforced here so a document cannot half-declare a venue or a period.
    """

    run_id: str
    strategies: tuple[StrategyEntry, ...]
    valuation: ValuationConfig
    instruments: tuple[str, ...]
    monitoring: MonitoringPolicy | None = None
    exchange: str | None = None
    execution_input_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    initial_account_snapshot: AccountSnapshot | None = None
    initial_account_mode: AccountMode | None = None

    def __post_init__(self) -> None:
        _require_id(self.run_id, "run_id")
        if not isinstance(self.strategies, tuple) or not self.strategies:
            raise ValueError("a run must name at least one strategy")
        if any(not isinstance(entry, StrategyEntry) for entry in self.strategies):
            raise TypeError("strategies must contain StrategyEntry values")
        ids = [entry.component_id for entry in self.strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("a run names each strategy at most once")
        if not isinstance(self.valuation, ValuationConfig):
            raise TypeError("valuation must be a ValuationConfig")
        if self.monitoring is not None and not isinstance(self.monitoring, MonitoringPolicy):
            raise TypeError("monitoring must be a MonitoringPolicy or None")
        if self.exchange is not None:
            _require_id(self.exchange, "exchange")
        if self.execution_input_id is not None:
            _require_id(self.execution_input_id, "execution_input_id")
        if (self.exchange is None) != (self.execution_input_id is None):
            raise ValueError("exchange and execution_input_id must be declared together")
        _require_period(self.start, self.end, "declared")
        object.__setattr__(
            self,
            "initial_account_snapshot",
            _require_account(self.initial_account_snapshot, self.initial_account_mode, "declared"),
        )
        _require_instruments(self.instruments)

    def strategy(self, component_id: str) -> StrategyEntry:
        for entry in self.strategies:
            if entry.component_id == component_id:
                return entry
        raise KeyError(
            f"run {self.run_id!r} does not name strategy {component_id!r}; it names "
            f"{', '.join(entry.component_id for entry in self.strategies)}"
        )


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

    def encoded(self) -> tuple[str, str, str, list[str]]:
        return (
            self.agenda_id,
            self.content_identity,
            self.provenance_identity,
            [occurrence.content_identity for occurrence in self.occurrences],
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
class FrozenRun:
    """Frozen owner declarations retained by a future preflight result.

    The run layer -- what every strategy shares -- plus the frozen strategies. `identity` is the
    run layer's alone, so adding a strategy to a run does not rename the rows the others wrote;
    `requirements`, `datasets` and `sources` are the union every strategy and constraint reads,
    which is the panel set (design §4.1).
    """

    run_id: str
    valuation: ValuationConfig
    valuation_agenda: FrozenAgenda
    strategies: tuple[FrozenStrategy, ...]
    monitoring: MonitoringPolicy | None = None
    monitoring_agenda: FrozenAgenda | None = None
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
        if not isinstance(self.valuation, ValuationConfig):
            raise TypeError("valuation must be a ValuationConfig")
        if not isinstance(self.valuation_agenda, FrozenAgenda):
            raise TypeError("valuation_agenda must be a FrozenAgenda")
        if self.valuation_agenda.agenda_id != self.valuation.agenda_id:
            raise ValueError("valuation_agenda must match valuation agenda_id")
        if self.valuation_agenda.agenda_role is not self.valuation.agenda_role:
            raise ValueError("valuation_agenda must match valuation agenda_role")
        if not isinstance(self.strategies, tuple) or not self.strategies:
            raise ValueError("a frozen run holds at least one strategy")
        if any(not isinstance(layer, FrozenStrategy) for layer in self.strategies):
            raise TypeError("strategies must contain FrozenStrategy values")
        ids = [layer.component_id for layer in self.strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("a frozen run holds each strategy at most once")
        if self.monitoring is not None and not isinstance(self.monitoring, MonitoringPolicy):
            raise TypeError("monitoring must be a MonitoringPolicy or None")
        if self.monitoring is None and self.monitoring_agenda is not None:
            raise ValueError("monitoring_agenda requires a monitoring policy")
        if self.monitoring is not None and not isinstance(self.monitoring_agenda, FrozenAgenda):
            raise TypeError("monitoring_agenda must be a FrozenAgenda when monitoring is set")
        if self.monitoring_agenda is not None:
            if self.monitoring_agenda.agenda_id != self.monitoring.agenda_id:
                raise ValueError("monitoring_agenda must match monitoring agenda_id")
            if self.monitoring_agenda.agenda_role is not self.monitoring.agenda_role:
                raise ValueError("monitoring_agenda must match monitoring agenda_role")
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

    def strategy(self, component_id: str) -> FrozenStrategy:
        for layer in self.strategies:
            if layer.component_id == component_id:
                return layer
        raise KeyError(
            f"run {self.run_id!r} froze no strategy {component_id!r}; it holds "
            f"{', '.join(layer.component_id for layer in self.strategies)}"
        )

    def dispatch_order(self, strategy: FrozenStrategy) -> tuple[OperationOccurrence, ...]:
        """The static occurrences one strategy's flow dispatches: its agenda and the run's."""
        return merged_occurrences(strategy.agenda, self.valuation_agenda, self.monitoring_agenda)

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
                # Valuation declares no data requirement: it reads the execution table the run
                # already fills against. Its agenda identity is carried in the agenda block below.
                "valuation": (self.valuation.agenda_id, str(self.valuation.agenda_role)),
                "monitoring": self.monitoring.agenda_id if self.monitoring is not None else None,
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
                "agendas": [
                    agenda.encoded()
                    for agenda in (self.valuation_agenda, self.monitoring_agenda)
                    if agenda is not None
                ],
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
