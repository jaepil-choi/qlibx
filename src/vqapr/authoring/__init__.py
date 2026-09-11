"""Transitional: the author surface's 0.15.0 import path, re-exporting `vqapr.component`.

``from vqapr.authoring import StrategyModel`` is what 0.15.0's skills, scaffolds and showcases are
written against. The classes live in `vqapr.component` -- one module per role, each base apart from
any shipped implementation -- and are published by `vqapr.public`. This module defines nothing; the
only importers inside the package are the root's lazy attribute and the shipped sample strategy,
both written for an author. It is removed in the release that renames the loop's vocabulary, after
which `vqapr.public` is the only author surface.
"""

from __future__ import annotations

from vqapr.component.account_view import EconomicAccountView
from vqapr.component.base import Component, Part, Tool
from vqapr.component.compliance.base import Compliance, ComplianceCall, ComplianceFinding
from vqapr.component.datamodel import DataCall, DataModel
from vqapr.component.reads import DatasetInput, requirements_for
from vqapr.component.strategy.base import StrategyCall, StrategyModel
from vqapr.component.strategy.decision import Hold, Rebalance
from vqapr.component.strategy.history import AccountHistory, AccountHistoryInput
from vqapr.component.strategy.recorder import TableSpec
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.observation import Observation
from vqapr.data.panel import PanelWindow

__all__ = (
    "AccountHistory",
    "AccountHistoryInput",
    "CalendarLookback",
    "Compliance",
    "ComplianceCall",
    "ComplianceFinding",
    "Component",
    "DataCall",
    "DataModel",
    "DatasetInput",
    "EconomicAccountView",
    "Hold",
    "InstantsLookback",
    "Observation",
    "PanelWindow",
    "Part",
    "Rebalance",
    "RowsLookback",
    "StrategyCall",
    "StrategyModel",
    "TableSpec",
    "Tool",
    "requirements_for",
)
