"""The StrategyModel role: from one current event, decide what to hold.

`StrategyCall` is what one decision is handed: the declared reads, the committed account and the
declared account history -- and nothing about the future. The decision returns a `Hold` or a
`Rebalance` (`decision.py`); its timing, identity and what it read are stamped by the engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import BinaryIO, ClassVar

from vqapr.component.account_view import EconomicAccountView
from vqapr.component.base import Part
from vqapr.component.strategy.decision import Hold, Rebalance
from vqapr.component.strategy.history import AccountHistory, AccountHistoryInput
from vqapr.component.strategy.recorder import InvocationRecorder, TableSpec
from vqapr.data.observation import Observation
from vqapr.data.panel import PanelWindow
from vqapr.domain.wiring import Role

__all__ = [
    "StrategyCall",
    "StrategyModel",
]


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


class StrategyModel(Part):
    """User extension that decides what to hold; its memory owns cadence and path-dependent rules.

    One class (record `132`). Two carried this name: this one, which the scaffold taught and an
    author subclassed, and an engine one the Flow ran, with an adapter between them that built the
    author's class fresh per callback and translated every argument and return. The adapter is
    gone; what an author writes is what the engine calls.

    **State is `memory`, as for every Model** (architecture 4.4, 5.1.1): strict JSON the Flow
    snapshots after a successful callback and restores before the next. `save_payload` /
    `load_payload` carry what memory cannot -- a fitted network, a large array -- as opaque bytes
    under the same commit. A fresh instance with both restored decides the same, and the Flow
    relies on that: nothing else about `self` is promised across a run boundary.

    **Rows go to `self.recorder`**, set by the Flow for the duration of one callback and `None`
    outside it, into the tables `tables()` declared. Writing to an undeclared table refuses.
    """

    recorder: InvocationRecorder | None = None

    ROLE: ClassVar[Role] = Role.STRATEGY_MODEL

    def tables(self) -> tuple[TableSpec, ...]:
        """Declare every table this Strategy may write during a callback. Empty by default."""
        return ()

    def account_history(self) -> AccountHistoryInput | None:
        """Declare which committed account values this Strategy reads back, and how far.

        `None` declares none: the run then retains only its current mark, so a Strategy that
        never looks at its own path costs nothing to carry one.
        """
        return None

    def save_payload(self, target: BinaryIO) -> None:
        """Persist private callback state that does not fit `memory` into Flow-owned staging.

        Preflight calls `save_payload` on a fresh instance, `load_payload` on another with those
        bytes, and `save_payload` again; the bytes must match before the first callback. So this
        must be deterministic -- no timestamp, no `id()`, no unordered set iteration.
        """

    def load_payload(self, source: BinaryIO) -> None:
        """Restore what `save_payload` wrote.

        A class with nothing to save yet must accept an EMPTY source: preflight round-trips the
        default `save_payload`, which writes no bytes, so an unguarded `pickle.load` refuses the
        run with `EOFError` before a single callback runs.
        """

    @abstractmethod
    def decide(self, call: StrategyCall) -> Hold | Rebalance:
        """Return the economic decision for this occurrence, and nothing else.

        `Hold` declines. `Rebalance` names one complete desired portfolio: weights, cash, and the
        budget they must satisfy. Everything an intent additionally carries -- its id, this
        Strategy's id, what was read, the account version seen -- is the Flow's to stamp, and a
        callback that tried to name any of it would be claiming authority it does not have.
        """
