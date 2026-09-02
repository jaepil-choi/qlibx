"""Model invocation contexts; capability absence is an intentional boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid5

from vqapr.account.history import AccountHistory
from vqapr.account.snapshot import AccountSnapshot
from vqapr.authoring import ConstraintBounds, ConstraintCall, DataCall, DatasetInput
from vqapr.data.windows import ModelWindow
from vqapr.models.calls import declared_rows, observations
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


def _unbounded() -> ConstraintBounds:
    """The bounds a callback sees when no Constraint is registered: no names, no limits."""
    return ConstraintBounds(lower_weights={}, upper_weights={})


class _DeclaredReads:
    """`read(alias)` over the aliases a Model declared in `inputs()`.

    Shared by all three contexts because all three roles read the same way -- that sameness is
    the point (`docs/issues/036`), so it is one implementation rather than three that agree today.

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
        # An alias is one requirement per declared field (`docs/issues/049`), so it is several
        # reads, joined back on `(instant, instrument)` -- the only pair every batch agrees on.
        # The author declared one thing and reads one thing; the fan-out is the engine's.
        return observations(
            declared_rows(lambda r: self.window.observations(r).rows, declared),
            instrument_field="instrument",
            available_at_field="available_at",
            fields=declared.fields,
        )


@dataclass(frozen=True, slots=True)
class ConstraintContext(_DeclaredReads, ConstraintCall):
    """What a Constraint may reach, and the third role to reach it the same way.

    Records `126` and `128` gave DataModel and StrategyModel one declaration (`inputs()`) and one
    read verb (`context.read(alias)`). A Constraint was still handed a `ModelWindow` and expected
    to call `window.observations(requirement)` on it -- a framework type and a second read shape,
    for the one extension point whose authoring class the loader would not even accept
    (`docs/issues/036`). This is that third role arriving.

    **No account.** `project` runs before any decision exists, to say what the feasible set is,
    and it never needed one. `monitor` receives an `EconomicAccountView` as its own argument
    instead, so the capability is present exactly where it is used and absent everywhere else.
    """

    window: ModelWindow
    instruments: tuple[str, ...] = ()
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")
        if not isinstance(self.instruments, tuple) or not all(
            isinstance(name, str) and name for name in self.instruments
        ):
            raise TypeError("instruments must be a tuple of non-empty strings")

    @property
    def evaluation_time(self):
        """The single frozen point-in-time cutoff this projection is bounded to."""
        return self.window.evaluation_time


@dataclass(frozen=True, slots=True)
class DataModelContext(_DeclaredReads, DataCall):
    """What a DataModel may reach: a cutoff and its declared reads, and nothing else.

    No account, no venue, no occurrence -- the absence is the definition of the role (architecture
    4.4). The one implementation of `authoring.DataCall`, the way `ConstraintContext` is of
    `ConstraintCall`.
    """

    window: ModelWindow
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)

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
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)
    constraint_bounds: ConstraintBounds = field(default_factory=_unbounded)
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
