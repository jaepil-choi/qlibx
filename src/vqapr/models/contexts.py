"""Model invocation contexts; capability absence is an intentional boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from vqapr.account.history import AccountHistory
from vqapr.authoring import (
    ConstraintBounds,
    ConstraintCall,
    DataCall,
    DatasetInput,
    EconomicAccountView,
    StrategyCall,
)
from vqapr.data.windows import ModelWindow
from vqapr.models.calls import declared_rows, observations
from vqapr.runtime.agendas import OperationOccurrence


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
class StrategyModelContext(_DeclaredReads, StrategyCall):
    """The complete capability surface for one Strategy callback.

    The one implementation of `authoring.StrategyCall`, the way the other two contexts are of
    their calls. `account` is the `EconomicAccountView` the Flow built from the committed
    snapshot and its last valuation -- the same view a monitoring Constraint sees (record `130`).
    The snapshot's `version` is not on it: that is a framework fact the Flow stamps onto the
    intent, and `_ENVELOPE_RESERVED_FIELDS` keeps it off every authored value.
    """

    occurrence: OperationOccurrence
    window: ModelWindow
    account: EconomicAccountView
    reads: Mapping[str, DatasetInput] = field(default_factory=dict)
    constraint_bounds: ConstraintBounds = field(default_factory=_unbounded)
    account_history: AccountHistory = field(default_factory=lambda: AccountHistory((), None))
    """What the Account itself recorded, bounded by this Strategy's declaration.

    Empty unless the Strategy declared an `AccountHistoryInput`. Reading an undeclared field
    raises rather than returning nothing, so a missing declaration fails loudly instead of
    silently disabling a rule that depends on it.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")
        if not isinstance(self.account, EconomicAccountView):
            raise TypeError("account must be an EconomicAccountView")
        if not isinstance(self.account_history, AccountHistory):
            raise TypeError("account_history must be an AccountHistory")
        if not isinstance(self.constraint_bounds, ConstraintBounds):
            raise TypeError("constraint_bounds must be a ConstraintBounds")
        object.__setattr__(self, "constraint_bounds", self.constraint_bounds.detached())

    @property
    def occurrence_id(self) -> str:
        return str(self.occurrence.occurrence_id)

    @property
    def evaluation_time(self):
        """The single frozen point-in-time cutoff this callback decides at."""
        return self.window.evaluation_time
