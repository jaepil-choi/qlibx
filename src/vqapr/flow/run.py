"""Closed declarations that establish operation ownership for a run."""

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
class RunDefinition:
    """Unresolved owner declarations; agenda references are never overridden here."""

    strategy: StrategyConfig
    valuation: ValuationConfig
    constraints: ConstraintSet
    monitoring: MonitoringPolicy | None = None
    exchange: ComponentRef | None = None
    execution_input_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    initial_account_snapshot: AccountSnapshot | None = None
    initial_account_mode: AccountMode | None = None
    initial_model_memory: ModelMemory = None

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategyConfig):
            raise TypeError("strategy must be a StrategyConfig")
        if not isinstance(self.valuation, ValuationConfig):
            raise TypeError("valuation must be a ValuationConfig")
        if not isinstance(self.constraints, ConstraintSet):
            raise TypeError("constraints must be a ConstraintSet")
        if self.monitoring is not None and not isinstance(self.monitoring, MonitoringPolicy):
            raise TypeError("monitoring must be a MonitoringPolicy or None")
        if self.exchange is not None:
            if not isinstance(self.exchange, ComponentRef):
                raise TypeError("exchange must be a ComponentRef or None")
            if self.exchange.kind is not ComponentKind.EXCHANGE:
                raise ValueError("exchange must identify an EXCHANGE component")
        if self.execution_input_id is not None and (
            not isinstance(self.execution_input_id, str) or not self.execution_input_id
        ):
            raise TypeError("execution_input_id must be a non-empty identifier or None")
        if (self.exchange is None) != (self.execution_input_id is None):
            raise ValueError("exchange and execution_input_id must be declared together")
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must be declared together")
        if self.start is not None and self.end is not None:
            require_tz_aware(self.start, name="start")
            require_tz_aware(self.end, name="end")
            if self.start.astimezone(UTC) > self.end.astimezone(UTC):
                raise ValueError("start must not be after end")
        if (self.initial_account_snapshot is None) != (self.initial_account_mode is None):
            raise ValueError(
                "initial_account_snapshot and initial_account_mode must be declared together"
            )
        if self.initial_account_snapshot is not None:
            if not isinstance(self.initial_account_snapshot, AccountSnapshot):
                raise TypeError("initial_account_snapshot must be an AccountSnapshot or None")
            if not isinstance(self.initial_account_mode, AccountMode):
                raise TypeError("initial_account_mode must be an AccountMode or None")
            snapshot = self.initial_account_snapshot
            object.__setattr__(
                self,
                "initial_account_snapshot",
                AccountSnapshot(snapshot.version, snapshot.cash, snapshot.positions),
            )
        object.__setattr__(
            self, "initial_model_memory", normalize_memory(self.initial_model_memory)
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


@dataclass(frozen=True, slots=True)
class FrozenRun:
    """Frozen owner declarations retained by a future preflight result."""

    strategy: StrategyConfig
    valuation: ValuationConfig
    constraints: ConstraintSet
    strategy_agenda: FrozenAgenda
    valuation_agenda: FrozenAgenda
    monitoring: MonitoringPolicy | None = None
    monitoring_agenda: FrozenAgenda | None = None
    exchange: ComponentRef | None = None
    execution_input: ExecutionInputRegistration | None = None
    start: datetime | None = None
    end: datetime | None = None
    initial_account_snapshot: AccountSnapshot | None = None
    initial_account_mode: AccountMode | None = None
    initial_model_memory: ModelMemory = None
    initial_payload: bytes = b""
    initial_model_state_ref: ModelStateRef = field(init=False)
    requirements: tuple[DataRequirement, ...] = ()
    datasets: tuple[DatasetRegistration, ...] = ()
    sources: tuple[SourceSpec, ...] = ()
    static_occurrences: tuple[OperationOccurrence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategyConfig):
            raise TypeError("strategy must be a StrategyConfig")
        if not isinstance(self.valuation, ValuationConfig):
            raise TypeError("valuation must be a ValuationConfig")
        if not isinstance(self.constraints, ConstraintSet):
            raise TypeError("constraints must be a ConstraintSet")
        if not isinstance(self.strategy_agenda, FrozenAgenda):
            raise TypeError("strategy_agenda must be a FrozenAgenda")
        if self.strategy_agenda.agenda_id != self.strategy.agenda_id:
            raise ValueError("strategy_agenda must match strategy agenda_id")
        if self.strategy_agenda.agenda_role is not self.strategy.agenda_role:
            raise ValueError("strategy_agenda must match strategy agenda_role")
        if not isinstance(self.valuation_agenda, FrozenAgenda):
            raise TypeError("valuation_agenda must be a FrozenAgenda")
        if self.valuation_agenda.agenda_id != self.valuation.agenda_id:
            raise ValueError("valuation_agenda must match valuation agenda_id")
        if self.valuation_agenda.agenda_role is not self.valuation.agenda_role:
            raise ValueError("valuation_agenda must match valuation agenda_role")
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
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must be frozen together")
        if self.start is not None and self.end is not None:
            require_tz_aware(self.start, name="start")
            require_tz_aware(self.end, name="end")
            if self.start.astimezone(UTC) > self.end.astimezone(UTC):
                raise ValueError("start must not be after end")
        if (self.initial_account_snapshot is None) != (self.initial_account_mode is None):
            raise ValueError(
                "initial_account_snapshot and initial_account_mode must be frozen together"
            )
        if self.initial_account_snapshot is not None:
            if not isinstance(self.initial_account_snapshot, AccountSnapshot):
                raise TypeError("initial_account_snapshot must be an AccountSnapshot or None")
            if not isinstance(self.initial_account_mode, AccountMode):
                raise TypeError("initial_account_mode must be an AccountMode or None")
            snapshot = self.initial_account_snapshot
            object.__setattr__(
                self,
                "initial_account_snapshot",
                AccountSnapshot(snapshot.version, snapshot.cash, snapshot.positions),
            )
        memory = normalize_memory(self.initial_model_memory)
        object.__setattr__(self, "initial_model_memory", memory)
        if not isinstance(self.initial_payload, bytes):
            raise TypeError("initial_payload must be bytes")
        object.__setattr__(self, "initial_payload", bytes(self.initial_payload))
        object.__setattr__(
            self,
            "initial_model_state_ref",
            _model_state_ref(memory, self.initial_payload),
        )
        if not isinstance(self.requirements, tuple) or not all(
            isinstance(requirement, DataRequirement) for requirement in self.requirements
        ):
            raise TypeError("requirements must be a tuple of DataRequirement values")
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
                DatasetRegistration(
                    dataset.dataset_id,
                    dataset.source,
                    dataset.instrument_field,
                    dataset.available_at,
                    dataset.key_fields,
                    MappingProxyType(dict(dataset.fields)),
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
        agendas = (self.strategy_agenda, self.valuation_agenda, self.monitoring_agenda)
        merged = tuple(
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
        if not isinstance(self.static_occurrences, tuple):
            raise TypeError("static_occurrences must be a tuple of OperationOccurrence values")
        if self.static_occurrences and self.static_occurrences != merged:
            raise ValueError("static_occurrences must be the deterministic agenda merge")
        object.__setattr__(self, "static_occurrences", merged)

    @property
    def identity(self) -> str:
        """Canonical identity of frozen declarations and static dispatch order."""
        return _identity(
            {
                "strategy": (
                    self.strategy.component.component_id,
                    self.strategy.component.fingerprint,
                ),
                "valuation": (
                    self.valuation.mark_requirement.consumer_id,
                    self.valuation.mark_requirement.dataset_id,
                    self.valuation.mark_requirement.fields,
                    repr(self.valuation.mark_requirement.lookback),
                ),
                "constraints": [
                    (constraint.component_id, constraint.fingerprint)
                    for constraint in self.constraints.constraints
                ],
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
                    (
                        agenda.agenda_id,
                        agenda.content_identity,
                        agenda.provenance_identity,
                        [occurrence.content_identity for occurrence in agenda.occurrences],
                    )
                    for agenda in (
                        self.strategy_agenda,
                        self.valuation_agenda,
                        self.monitoring_agenda,
                    )
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
                "initial_model_memory": self.initial_model_memory,
                "initial_model_state_ref": (self.initial_model_state_ref.digest),
                "initial_payload": self.initial_payload.hex(),
                "requirements": [
                    (
                        requirement.consumer_id,
                        requirement.dataset_id,
                        requirement.fields,
                        repr(requirement.lookback),
                    )
                    for requirement in self.requirements
                ],
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
