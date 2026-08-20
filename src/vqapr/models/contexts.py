"""Model invocation contexts; capability absence is an intentional boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from vqapr.account.history import AccountHistory
from vqapr.account.snapshot import AccountSnapshot
from vqapr.constraints.constraint import ConstraintBounds
from vqapr.data.windows import ModelWindow
from vqapr.runtime.agendas import OperationOccurrence


@dataclass(frozen=True, slots=True)
class DataModelContext:
    window: ModelWindow

    def __post_init__(self) -> None:
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")


@dataclass(frozen=True, slots=True)
class StrategyModelContext:
    """The complete capability surface for one Strategy callback."""

    occurrence: OperationOccurrence
    window: ModelWindow
    account: AccountSnapshot
    constraint_bounds: ConstraintBounds = field(default_factory=lambda: ConstraintBounds({}, {}))
    account_history: AccountHistory = field(
        default_factory=lambda: AccountHistory((), None)
    )
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
