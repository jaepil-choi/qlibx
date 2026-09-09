"""The three call surfaces, one per role.

A Component is called back on an event and handed a call: the complete, bounded set of what it may
reach at that instant, and nothing else. The three are abstract because the engine implements them
(`context.py`) and the author only receives one -- a type to annotate against, not a class to
subclass.

What differs between them is exactly what the roles differ in. A `DataCall` has a cutoff and its
declared reads. A `StrategyCall` adds the account view and its declared history. A
`ComplianceCall` adds the instruments the run declared; the committed account it observes is its
own argument.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from vqapr.authoring.history import AccountHistory
from vqapr.authoring.view import EconomicAccountView
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
    else: the committed account and its own declared history. Framework facts -- the account
    version, the intent id, what was read -- are not here; the Flow stamps them onto the intent
    itself (record `125`). The box it builds inside is its own to compute
    (`vqapr.portfolio.bounds`, design §7.1): nothing projects one for it.
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


class ComplianceCall(ABC):
    """The bounded capability surface for one Compliance observation.

    An abstract contract, like `DataCall` and `StrategyCall`; `vqapr.authoring.context` supplies
    the one concrete implementation. The committed account the rule observes is `observe`'s own
    argument rather than a member here, so the capability is present exactly where it is used.
    """

    @property
    @abstractmethod
    def evaluation_time(self) -> datetime:
        """The market-clock instant this observation is bounded to: when the book was marked."""

    @property
    @abstractmethod
    def instruments(self) -> tuple[str, ...]:
        """Every instrument the run declared, in the run's declared order."""

    @abstractmethod
    def read(self, alias: str, field: str) -> PanelWindow:
        """One field of a panel-grain alias declared in `Compliance.inputs()`, as a 2d window.

        `instants` x `instruments`, a slice of the panel the run built once; `current()` is the
        cross-section at the window's last instant, `latest()` the newest value per name anywhere
        in it. Refused on a `rows`-grain alias, which is read with `rows`.
        """

    @abstractmethod
    def rows(self, alias: str) -> tuple[Observation, ...]:
        """PIT observations for one `rows`-grain alias declared in `Compliance.inputs()`.

        One `Observation` per (instant, instrument), every declared field on it. Refused on a
        panel-grain alias, which is read with `read(alias, field)`.
        """
