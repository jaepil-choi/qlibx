"""Closed monitoring ownership declarations."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.domain.identifiers import AgendaId
from vqapr.runtime.agendas import OperationRole


@dataclass(frozen=True, slots=True)
class MonitoringPolicy:
    """Monitoring owns only its independent operation agenda."""

    agenda_id: AgendaId
    agenda_role: OperationRole

    def __post_init__(self) -> None:
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.agenda_role, OperationRole):
            raise TypeError("agenda_role must be an OperationRole")
        if self.agenda_role is not OperationRole.MONITORING:
            raise ValueError("monitoring agenda_role must be MONITORING")
