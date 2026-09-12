"""The DataModel role: data in, a dataset out, and no account in between.

Nothing a DataModel returns is executed. It sees no account and passes through no venue, and its
rows become a registered dataset any number of runs may read. `DataCall` is what one computation is
handed: its cutoff and its declared reads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar

from vqapr.component.base import Call, Part
from vqapr.data.observation import Observation
from vqapr.data.panel import PanelWindow
from vqapr.domain.rows import Rows
from vqapr.domain.wiring import Role

__all__ = [
    "DataCall",
    "DataModel",
]


class DataCall(Call, ABC):
    """The complete, bounded capability surface for one DataModel invocation."""

    @property
    @abstractmethod
    def at(self) -> datetime:
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


class DataModel(Part):
    """A Component whose result is values: data in, a dataset out, and no account in between.

    **What makes it a DataModel is that nothing it returns is executed** (architecture 4.4). It
    sees no account, passes through no venue, and its rows become a registered dataset that any
    number of runs may then read. The other role, `StrategyModel`, differs by exactly that.

    **A row is a dict**: `{"instrument": name, "<field>": value, ...}`, one per instrument, with
    the fields the materialization declared and nothing the package owns -- `available_at` is
    stamped by the framework, and a row that tries to carry one is refused. The shape of the
    dataset being produced is a declaration and lives with the materialization; what the model
    does is compute, and it says nothing about the schema twice.

    Reads arrive as `Observation` records through `call.read(alias)`, the same verb every role
    uses.
    """

    ROLE: ClassVar[Role] = Role.DATA_MODEL

    @abstractmethod
    def compute(self, call: DataCall) -> Rows:
        """Compute this instant's rows from the declared reads. One dict per instrument."""
