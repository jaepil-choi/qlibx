"""Closed valuation ownership declarations."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.domain.identifiers import AgendaId
from vqapr.runtime.agendas import OperationRole


@dataclass(frozen=True, slots=True)
class ValuationConfig:
    """Valuation's agenda.

    Valuation declares no data requirement. The book is valued from the prices the venue
    published as executable at the execution instant, which the run already reads to fill
    against. Subscribing to a second price source would give one run two answers for what its
    own book is worth, and the observation-priced answer is the one it could not have traded at.
    """

    agenda_id: AgendaId
    agenda_role: OperationRole

    def __post_init__(self) -> None:
        if not isinstance(self.agenda_id, str) or not self.agenda_id:
            raise TypeError("agenda_id must be an AgendaId")
        if not isinstance(self.agenda_role, OperationRole):
            raise TypeError("agenda_role must be an OperationRole")
        if self.agenda_role is not OperationRole.VALUATION:
            raise ValueError("valuation agenda_role must be VALUATION")
