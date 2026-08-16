"""Model invocation contexts; capability absence is an intentional boundary."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.account.snapshot import AccountSnapshot
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

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence, OperationOccurrence):
            raise TypeError("occurrence must be an OperationOccurrence")
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")
        if not isinstance(self.account, AccountSnapshot):
            raise TypeError("account must be an AccountSnapshot")
