"""Model invocation contexts; capability absence is an intentional boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid5

from vqapr.account.history import AccountHistory
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import ConstraintBounds
from vqapr.data.requirements import DataRequirement
from vqapr.data.windows import ModelWindow
from vqapr.models.calls import observations
from vqapr.portfolio.budgets import Budget
from vqapr.portfolio.intents import (
    EconomicPortfolioIntent,
    IntentSourceRef,
    PortfolioTarget,
)
from vqapr.runtime.agendas import OperationOccurrence

_INTENT_NAMESPACE = UUID("6f0d5b1e-7c94-4a3f-9b28-1e5a7d0c4f62")
"""Namespace for intent ids derived from a strategy and its occurrence.

Deriving the id means two runs of the same strategy over the same agenda produce the same intent
identity, which is what makes a replay comparable to the run it replays.
"""


class _DeclaredReads:
    """`read(alias)` over the aliases a Model declared in `inputs()`.

    Shared by both contexts because both roles read the same way -- that sameness is the point
    (`docs/issues/036`), so it is one implementation rather than two that agree today.

    `reads` is empty for a Model that declares its requirements the older way, by overriding
    `requirements()` and reaching `context.window.observations(...)` itself. Both paths run; the
    window is the same object underneath, so a mixed tree behaves identically either way.
    """

    __slots__ = ()

    def read(self, alias: str) -> tuple:
        if not isinstance(alias, str):
            raise TypeError("alias must be a string")
        declared = self.reads.get(alias)
        if declared is None:
            known = ", ".join(sorted(self.reads)) or "nothing"
            raise KeyError(
                f"{alias!r} was not declared in inputs(); this model declared: {known}"
            )
        # One requirement per alias today, and `requirements_for` already returns a tuple against
        # the day an alias fans out into one requirement per field (`docs/issues/049`). Joining
        # them belongs here, where the alias is still a single thing to the author.
        rows: list = []
        fields: list[str] = []
        for requirement in declared:
            rows.extend(self.window.observations(requirement).rows)
            fields.extend(requirement.fields)
        return observations(rows, fields=tuple(dict.fromkeys(fields)))


@dataclass(frozen=True, slots=True)
class DataModelContext(_DeclaredReads):
    window: ModelWindow
    reads: Mapping[str, tuple[DataRequirement, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")

    @property
    def evaluation_time(self):
        """The single frozen point-in-time cutoff this invocation computes at."""
        return self.window.evaluation_time


@dataclass(frozen=True, slots=True)
class StrategyModelContext(_DeclaredReads):
    """The complete capability surface for one Strategy callback."""

    occurrence: OperationOccurrence
    window: ModelWindow
    account: AccountSnapshot
    reads: Mapping[str, tuple[DataRequirement, ...]] = field(default_factory=dict)
    constraint_bounds: ConstraintBounds = field(default_factory=lambda: ConstraintBounds({}, {}))
    account_history: AccountHistory = field(default_factory=lambda: AccountHistory((), None))
    """What the Account itself recorded, bounded by this Strategy's declaration.

    Empty unless the Strategy declared an `AccountRequirement`. Reading an undeclared field
    raises rather than returning nothing, so a missing declaration fails loudly instead of
    silently disabling a rule that depends on it.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")
        if not isinstance(self.account, AccountSnapshot):
            raise TypeError("account must be an AccountSnapshot")
        if not isinstance(self.account_history, AccountHistory):
            raise TypeError("account_history must be an AccountHistory")
        if not isinstance(self.constraint_bounds, ConstraintBounds):
            raise TypeError("constraint_bounds must be a ConstraintBounds")
        object.__setattr__(
            self,
            "account",
            AccountSnapshot(
                version=self.account.version,
                cash=self.account.cash,
                positions=self.account.positions,
            ),
        )
        object.__setattr__(self, "constraint_bounds", self.constraint_bounds.detached())

    def source_refs(self) -> tuple[IntentSourceRef, ...]:
        """Provenance for exactly the sources this callback has read so far.

        Lineage is a fact about the window, not a judgement the Strategy makes. The Flow already
        derives this same value from the same accesses and refuses an intent that disagrees with
        it, so asking a Strategy to assemble it by hand is asking it to transcribe an answer that
        is checked against the original -- and a Strategy that forgets leaves its intent with no
        provenance at all.

        Call it after the reads it should cover; accesses recorded later are not in it.
        """
        seen: dict[str, str] = {}
        for access in self.window.accesses:
            seen.setdefault(str(access.source_id), access.source_digest)
        return tuple(IntentSourceRef(source, digest) for source, digest in seen.items())

    def intent(
        self,
        weights: Mapping[str, Decimal],
        *,
        budget: Budget,
        strategy_id: str,
        cash_target: Decimal | None = None,
        model_state_ref: object = None,
    ) -> EconomicPortfolioIntent:
        """Build the intent this callback decided on, filling in what the context already knows.

        Of the eight values an `EconomicPortfolioIntent` carries, five are mechanical: the id is
        derived from this occurrence, the targets are the weights sorted, the cash target is
        whatever the weights leave over, the provenance is the window's, and the account version
        is the one the callback was handed. Only the weights, the budget and the strategy's own
        identity are decisions.

        Writing the mechanical five by hand at every callback is five chances to write one
        differently. `cash_target` stays overridable because a Strategy may intend to hold cash
        beyond its unallocated remainder.
        """
        allocated = sum(weights.values(), Decimal(0))
        targets = tuple(
            PortfolioTarget(instrument, weight=weight)
            for instrument, weight in sorted(weights.items())
        )
        return EconomicPortfolioIntent(
            uuid5(_INTENT_NAMESPACE, f"{strategy_id}/{self.occurrence.occurrence_id}"),
            strategy_id,
            targets,
            Decimal(1) - allocated if cash_target is None else cash_target,
            budget,
            self.source_refs(),
            self.account.version,
            model_state_ref,
        )
