"""Closed valuation ownership declarations."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.data.requirements import DataRequirement
from vqapr.domain.identifiers import AgendaId
from vqapr.runtime.agendas import OperationRole


@dataclass(frozen=True, slots=True)
class ValuationConfig:
    """Valuation's agenda and the field used to mark every residual holding."""

    agenda_id: AgendaId
    agenda_role: OperationRole
    mark_requirement: DataRequirement

    def __post_init__(self) -> None:
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.agenda_role, OperationRole):
            raise TypeError("agenda_role must be an OperationRole")
        if self.agenda_role is not OperationRole.VALUATION:
            raise ValueError("valuation agenda_role must be VALUATION")
        if not isinstance(self.mark_requirement, DataRequirement):
            raise TypeError("mark_requirement must be a DataRequirement")
        if len(self.mark_requirement.fields) != 1:
            raise ValueError("mark_requirement must bind exactly one mark field")
