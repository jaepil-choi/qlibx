"""The three call surfaces, one per role.

A Component is called back on an event and handed a call: the complete, bounded set of what it may
reach at that instant, and nothing else. The three are abstract because the engine implements them
(`context.py`) and the author only receives one -- a type to annotate against, not a class to
subclass.

What differs between them is exactly what the roles differ in. A `DataCall` has a cutoff and its
declared reads. A `StrategyCall` adds the account view, the constraint bounds and the recorder. A
`ConstraintCall` sees the account and the targets under test.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from vqapr.authoring.history import AccountHistory
from vqapr.authoring.view import ConstraintBounds, EconomicAccountView
from vqapr.data.panel import PanelWindow
from vqapr.domain.shapes import Observation


class DataCall(ABC):
    """The complete, bounded capability surface for one DataModel invocation."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this invocation computes for."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `DataModel.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `DataModel.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """


class StrategyCall(ABC):
    """The complete, bounded capability surface for one Strategy occurrence.

    `StrategyModelContext` is its one implementation, the way `DataModelContext` is of
    `DataCall`. What a Strategy receives beyond a DataModel is what its role needs and nothing
    else: the committed account, its own declared history, and the bounds every registered
    Constraint projected. Framework facts -- the account version, the intent id, what was read --
    are not here; the Flow stamps them onto the intent itself (record `125`).
    """

    @property
    @abstractmethod
    def occurrence_id(self) -> str:
        """Which occurrence this is. Kept in `memory`, it is how a cadence rule counts."""

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen PIT cutoff this occurrence decides at."""

    @property
    @abstractmethod
    def account(self) -> EconomicAccountView:
        """The committed Account: cash, positions, and the marks of its last valuation."""

    @property
    @abstractmethod
    def account_history(self) -> AccountHistory:
        """Committed account history, bounded by this Strategy's own `account_history()`."""

    @property
    @abstractmethod
    def constraint_bounds(self) -> ConstraintBounds:
        """The merged bounds projected from every registered Constraint."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `StrategyModel.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `StrategyModel.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """


class ConstraintCall(ABC):
    """The bounded capability surface for one Constraint invocation.

    **An abstract contract, like `DataCall` and `StrategyCall`, and no longer a value.** It was a
    concrete frozen dataclass that nothing in `src/` ever built -- only tests -- while the engine
    handed a Constraint a `ModelWindow` and a tuple of instruments instead.
    `vqapr.authoring.context` now supplies the one concrete implementation, the same way it does
    for the other two roles.

    **The account came off it.** It used to carry an `EconomicAccountView`, which meant `project`
    -- the member that runs before any decision exists, to say what the feasible set is -- was
    handed the committed account. Nothing needed it and the engine never offered it, so the
    authoring shape was granting authority the engine did not. Where the two contracts disagreed
    about how much a member may see, the narrower one is right (architecture 2.2, least
    authority): `monitor` receives the account as its own argument, and `project` cannot reach one.
    """

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The single frozen point-in-time cutoff this invocation is bounded to."""

    @property
    @abstractmethod
    def instruments(self) -> tuple[str, ...]:
        """Every instrument this projection must cover, in the run's declared order."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `Constraint.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `Constraint.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """
