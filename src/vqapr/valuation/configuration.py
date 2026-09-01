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

    **A valuation agenda cannot mark more often than the strategy agenda creates execution
    instants.** A valuation occurrence reports the mark the Account already committed; it does not
    derive a new one. Marks are committed at execution instants, and those exist only where a
    callback produced an intent or a ``Hold`` that took a pending valuation. So a daily
    valuation agenda over a *monthly* strategy agenda yields a monthly NAV series -- nothing
    refuses, the series is simply as sparse as the strategy's cadence. A daily series needs a
    daily **strategy** cadence, with the rebalance rule held in the Model's memory, which is where
    cadence belongs.
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
