"""Stateful Strategy occurrence-callback contract.

**The callback returns economics, and the Flow stamps identity.** Record `125`. Until then this
contract asked a Strategy for a whole `EconomicPortfolioIntent` -- eight fields, of which five are
facts only the framework can know: the intent's UUID, the strategy id, the provenance of every
source the callback read, the account version it saw, and the visible model-state ref. An author
who got one wrong produced an intent the Flow refused; an author who got one *plausibly* wrong
produced one it accepted under the wrong identity.

The Flow was already deriving all five in order to check the author's copy against them
(`flow/simulation.py::_validate_intent_authority`, and `_actual_source_refs` beside it). Stamping
what it already derives is strictly less code than receiving and comparing it, and it removes a
whole class of authoring error rather than reporting it.

So the return type is now the same `Hold | Rebalance` an author writes against
`vqapr.authoring` -- one decision algebra, not two. `NoDecision` was the second spelling of `Hold`
and is gone; `DataModel.compute` has always worked this way, refusing an author-set `available_at`
outright (`flow/materialize.py`), and this brings the Strategy side to the same rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO

from vqapr.account.history import AccountRequirement

# The authoring contract is the contract. `vqapr.authoring` imports nothing from `models/`, so
# this direction is the one that carries no cycle -- and it is the direction the surface ruling
# picked: what an author writes is what the engine accepts, with no translation in between.
from vqapr.authoring import Hold, Rebalance
from vqapr.evidence.recorder import InvocationRecorder
from vqapr.evidence.tables import TableSpec
from vqapr.models.contexts import StrategyModelContext
from vqapr.models.memory import ModelMemory
from vqapr.models.model import Model


class StrategyModel(Model, ABC):
    """User extension whose memory owns cadence and other path-dependent rules."""

    memory: ModelMemory = None
    recorder: InvocationRecorder | None = None

    def tables(self) -> tuple[TableSpec, ...]:
        """Declare diagnostic tables available during one callback invocation."""
        return ()

    def account_requirements(self) -> tuple[AccountRequirement, ...]:
        """Declare which of the Account's own committed values this Strategy reads.

        Declaring nothing means the run keeps only its current mark, so a Strategy that does not
        look at its realised path costs nothing to carry one.
        """
        return ()

    def save_payload(self, target: BinaryIO) -> None:
        """Persist private callback state into Flow-owned staging."""

    def load_payload(self, source: BinaryIO) -> None:
        """Restore private callback state from Flow-owned staging."""

    @abstractmethod
    def on_occurrence(self, context: StrategyModelContext) -> Hold | Rebalance:
        """Return the economic decision for this occurrence, and nothing else.

        `Hold` declines. `Rebalance` names one complete desired portfolio: weights, cash, and the
        budget they must satisfy. Everything an intent additionally carries -- its id, this
        Strategy's id, what was read, the account version seen -- is the Flow's to stamp, and a
        callback that tried to name any of it would be claiming authority it does not have.
        """
