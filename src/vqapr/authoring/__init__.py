"""Agent-first extension authoring/read/result contracts.

The sole public home for what an author subclasses (``Component`` and its roles ``DataModel``,
``StrategyModel``, ``Compliance``), receives (``DataCall``, ``StrategyCall``, ``ComplianceCall``,
``PanelWindow``, ``Observation``, ``EconomicAccountView``, ``AccountHistory``,
``AccountHistory``), and returns (``Rows``, ``Hold``/``Rebalance``, ``ComplianceFinding``).

Every public declaration here is a frozen, keyword-only value unless shown otherwise by the
approved algebra (``Observation`` is positional; ``DataCall``, ``StrategyCall``, ``DataModel``,
``StrategyModel``, and ``Compliance`` are abstract call/extension contracts, not values). What an
author constructs and hands to the engine -- ``DatasetInput``, ``AccountHistoryInput``,
``Hold``, ``Rebalance``, ``ComplianceFinding`` -- is a strict pydantic
model (owner ruling 2026-09-08): a wrong type is refused rather than coerced, and the refusal is
a ``pydantic.ValidationError``, which is a ``ValueError``. Constructors reject duplicate names,
empty identifiers, naive datetimes, non-finite ``Decimal`` values, and author-supplied
framework-envelope fields. Incoming mappings are copied into read-only sorted views; incoming
sequences become detached tuples.

**The package invariant: everything a Component sees, and nothing above it.** This replaces the
module's older wording, *"pure algebra: it declares contracts only; no runtime adapter, store,
catalog, or Flow wiring lives here"*, which was true of one file and could not survive the split
(record `192`). ``context.py`` is why: it is the engine's implementation of the three call
contracts, it binds a `ModelWindow` to a callback, and it is what a user constructs by hand to
test their own Component. It is not wiring the author is kept away from -- it is the object the
author is handed, spelled concretely. What the invariant still forbids is the direction: nothing
under `authoring/` may import `exchange/`, `extension/`, `project/`, `flow/` or the facade, and
`tests/boundaries/test_the_layers_hold.py` is where that is enforced rather than promised.

**This `__init__` re-exports; almost no other package's does.** The convention in this tree is that
`__init__.py` carries the package's argument and nothing else -- import the module. Two packages
are exceptions, for two different reasons. `record/` hides its module layout deliberately. This one
is a **published import path**: ``from vqapr.authoring import StrategyModel`` is what the shipped
skills, the emitted scaffolds and every showcase are written against, so the split below it must
not reach them. The nine modules are an implementation detail of this door.

Layered so the door has no cycle behind it: ``_validation`` at the bottom, then ``reads``,
``history``, ``view`` and ``result``, then ``call``, then ``component`` at the top. ``records`` is
independent of all of them and ``context`` sits above everything, being the engine's realisation of
what the rest declares.
"""

from __future__ import annotations

from vqapr.authoring.call import ComplianceCall, DataCall, StrategyCall
from vqapr.authoring.component import Compliance, Component, DataModel, Part, StrategyModel, Tool
from vqapr.authoring.history import AccountHistory, AccountHistoryInput
from vqapr.authoring.reads import DatasetInput, requirements_for
from vqapr.authoring.records import TableSpec
from vqapr.authoring.result import ComplianceFinding, Hold, Rebalance
from vqapr.authoring.view import EconomicAccountView
from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.panel import PanelWindow
from vqapr.domain.shapes import Observation

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
