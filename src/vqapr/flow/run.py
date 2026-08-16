"""Closed declarations that establish operation ownership for a run."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.domain.identifiers import AgendaId
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig


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

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, StrategyConfig):
            raise TypeError("strategy must be a StrategyConfig")
        if not isinstance(self.valuation, ValuationConfig):
            raise TypeError("valuation must be a ValuationConfig")
        if not isinstance(self.constraints, ConstraintSet):
            raise TypeError("constraints must be a ConstraintSet")
        if self.monitoring is not None and not isinstance(self.monitoring, MonitoringPolicy):
            raise TypeError("monitoring must be a MonitoringPolicy or None")


@dataclass(frozen=True, slots=True)
class FrozenAgenda:
    """A resolved owner agenda identity and its inclusive run slice."""

    agenda_id: AgendaId
    agenda_role: OperationRole
    occurrences: tuple[OperationOccurrence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.agenda_role, OperationRole):
            raise TypeError("agenda_role must be an OperationRole")
        if not isinstance(self.occurrences, tuple):
            raise TypeError("occurrences must be a tuple of OperationOccurrence values")
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
