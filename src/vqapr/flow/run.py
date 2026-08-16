"""Closed declarations that establish operation ownership for a run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.domain.identifiers import AgendaId
from vqapr.domain.timestamps import require_tz_aware
from vqapr.exchange.execution_table import ExecutionInputRegistration
from vqapr.extension.component import ComponentKind, ComponentRef
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


def _freeze_declaration(value: object, *, name: str) -> object:
    """Retain only simple immutable initial declarations until state ownership exists."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, tuple):
        return tuple(_freeze_declaration(item, name=name) for item in value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError(f"{name} mapping keys must be strings")
        return MappingProxyType(
            {key: _freeze_declaration(item, name=name) for key, item in sorted(value.items())}
        )
    raise TypeError(f"{name} must be an immutable declaration")


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
    initial_account: object | None = None
    initial_model_state: object | None = None

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
        object.__setattr__(
            self,
            "initial_account",
            _freeze_declaration(self.initial_account, name="initial_account"),
        )
        object.__setattr__(
            self,
            "initial_model_state",
            _freeze_declaration(self.initial_model_state, name="initial_model_state"),
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
    initial_account: object | None = None
    initial_model_state: object | None = None
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
        object.__setattr__(
            self,
            "initial_account",
            _freeze_declaration(self.initial_account, name="initial_account"),
        )
        object.__setattr__(
            self,
            "initial_model_state",
            _freeze_declaration(self.initial_model_state, name="initial_model_state"),
        )
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
        occurrence_ids = [occurrence.occurrence_id for occurrence in merged]
        if len(set(occurrence_ids)) != len(occurrence_ids):
            raise ValueError("static occurrence IDs must be unique across agendas")
        object.__setattr__(self, "static_occurrences", merged)

    @property
    def identity(self) -> str:
        """Canonical identity of frozen declarations and static dispatch order."""
        return _identity(
            {
                "strategy": self.strategy.component.fingerprint,
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
                "exchange": self.exchange.fingerprint if self.exchange is not None else None,
                "execution_input": (
                    self.execution_input.execution_input_id
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
                "initial_account": self.initial_account,
                "initial_model_state": self.initial_model_state,
            }
        )

    @property
    def physical_source_guarantee(self) -> str:
        """The freeze covers declarations, not source bytes."""
        return "Configuration and declaration objects are frozen; physical source bytes are not."
