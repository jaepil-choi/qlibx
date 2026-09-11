"""The Compliance role: an observer of the committed, marked account on the market clock.

Right after VALUATION at every market-clock instant, each rule a run declared observes the book the
venue actually left -- with its own parameters, reading its own declared data as of that instant --
and returns a `ComplianceFinding`: whether it passed, what it measured, the bound, the excess and
who offended. It changes nothing. Which rule measured is stamped by the framework, and the tolerance
is judged by the framework once for every rule (`report.py`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import ClassVar

from pydantic import BaseModel, field_validator

from vqapr.component._validation import (
    _ENVELOPE_RESERVED_FIELDS,
    _VALUE_CONFIG,
    _copy_values,
    _identifier,
)
from vqapr.component.account_view import EconomicAccountView
from vqapr.component.base import Call, Tool
from vqapr.data.observation import Observation
from vqapr.data.panel import PanelWindow
from vqapr.domain.wiring import Role

__all__ = [
    "Compliance",
    "ComplianceCall",
    "ComplianceFinding",
]


class ComplianceCall(Call, ABC):
    """The complete, bounded capability surface for one Compliance observation.

    An abstract contract, like `DataCall` and `StrategyCall`; `vqapr.run.engine.calls` supplies
    the one concrete implementation. Everything a rule may reach is here -- its declared reads
    as of the instant, the run's instruments, and the committed, marked account -- and nothing
    is handed beside it (record `229`): a role's Call is the whole of its authority, which is
    what makes point-in-time correctness a matter of what a rule cannot reach rather than of
    what it remembers not to do. The wiring table already said so (`COMMITTED_ACCOUNT` is a View
    Compliance receives); the signature now agrees.
    """

    @property
    @abstractmethod
    def account(self) -> EconomicAccountView:
        """The committed account, marked at this instant.

        `weight(instrument_id)` is the derivation a weight-based rule wants; `positions` and
        `values` are there for a rule that asks about quantity or about money.
        """

    @property
    @abstractmethod
    def at(self) -> datetime:
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


class Compliance(Tool):
    """User extension contract: an observer of the committed account, on the market clock.

    Design §7.2 (`docs/design/two-clocks-and-the-wiring-table.md`):

        Compliance   on the market clock, right after VALUATION
                     subscribes . remembers . observes the committed account . leaves a finding
                     changes nothing (PRD §6.8)

    **One member, because observing is one thing.** The old `Constraint` had two -- `project`,
    which bounded construction before anything was decided, and `monitor`, which judged the
    committed book -- and the two lived on different clocks with different memory semantics
    (bounds are stateless, observation counts). Construction is best effort and best effort is the
    strategy's discretion, so the projection became a kit of pure functions the strategy calls
    (`vqapr.portfolio.bounds`, design §7.1). What remained is the fact the framework guarantees:
    every market-clock instant, after the book is marked, each declared rule sees it.

    **Independent parameters, deliberately.** A rule is not handed the box the strategy built
    inside, and it does not inherit the strategy's targets. A watcher that inherits the target of
    the thing it watches is grading itself; two numbers that differ are information, and the
    report keeps them side by side (owner decision, design §7.2).

    **A breach does not stop a run.** It is recorded -- which rule, what the limit was, what was
    measured, who offended -- in `vqapr.monitoring`, one row per rule per instant, and counted in
    the strategy record's `contract` block.

    **The id is declared once, here, and not repeated on every finding.** `compliance_id` says
    which rule this is and is checked at load against the id it was registered under, so a rule
    registered as `noshort` and answering to `no-short` is refused before a run is spent.
    """

    ROLE: ClassVar[Role] = Role.COMPLIANCE

    @property
    @abstractmethod
    def compliance_id(self) -> str:
        """The id this rule answers to. Must equal the id it is registered under."""

    @property
    def tolerance(self) -> Decimal | None:
        """How far past a bound the realised book may land and still count as inside it.

        `None`, the default, leaves it to the framework: ``max(bound * 1%, 10bp of NAV)``. A book
        executes in whole lots and is marked after its fills, so the realised weight lands a little
        off the target the optimiser put on the grid; without a tolerance that residue is filed as a
        violation in the same counter as a real one (`docs/issues/archive/086`). Override with a
        `Decimal` share of NAV to tighten or loosen it. The comparison itself stays the author's:
        `observe` returns `passed`, `measured`, `bound`, `excess`, and the framework judges the
        excess against this line once, for every rule, and reports the verdict beside the author's
        -- `held` / `within_tolerance` / `breached` -- so nothing is hidden.
        """
        return None

    @abstractmethod
    def observe(self, call: ComplianceCall) -> ComplianceFinding:
        """Measure the committed, marked account at the market-clock instant it was marked at.

        `call.account.weight(instrument_id)` is the derivation a weight-based rule wants;
        `positions` and `values` are there for a rule that asks about quantity or about money.
        `call` also carries the rule's own declared reads as of that instant -- one Call, the
        whole of the rule's authority (record `229`) -- and its `memory` was restored before this
        call and is committed after it, so a rule that counts can count.
        """


class ComplianceFinding(BaseModel):
    """One Compliance rule's complete, immutable result for one economic observation.

    **`offenders` is a field and not a `details` key**, because it is the one thing a refusal
    cannot be written without. `docs/implementations/086` is a run that stopped on a 20% cap and
    said only *"economic intent violates projected constraints"*, leaving a first-time user to
    re-run the strategy without the rule and read the weight table to find out which name
    breached it.
    The refusal names them now, and it can only do that if every finding carries them under one
    name -- a convention inside a free-form mapping is not something a message can rely on.

    It also could not live there. `details` admits portable scalars only, so that a diagnostic
    mapping survives being written to a record and read back; a tuple is refused. Promoting the
    field keeps that rule intact instead of widening it for one caller.
    """

    model_config = _VALUE_CONFIG

    passed: bool
    measured: Decimal
    bound: Decimal
    excess: Decimal
    details: Mapping[str, object]
    offenders: tuple[str, ...] = ()

    @field_validator("offenders", mode="before")
    @classmethod
    def _named_once(cls, value: object) -> tuple[str, ...]:
        # Not `_unique_identifiers`, which requires at least one entry: an empty `offenders` is
        # the ordinary passing case and the most common value this field ever holds.
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise TypeError("offenders must be a sequence of instrument ids")
        offenders = tuple(_identifier(entry, name="offenders entry") for entry in value)
        if len(set(offenders)) != len(offenders):
            raise ValueError("offenders entries must be unique")
        return offenders

    @field_validator("details", mode="before")
    @classmethod
    def _portable(cls, value: object) -> Mapping[str, object]:
        details = _copy_values(value, name="details", reserved=_ENVELOPE_RESERVED_FIELDS)
        if len(details) > 32:
            raise ValueError("details must be bounded to 32 semantic keys")
        return details

    @field_validator("details")
    @classmethod
    def _read_only(cls, value: Mapping[str, object]) -> Mapping[str, object]:
        # pydantic hands the mapping back as a dict; what an author reads is a view.
        return MappingProxyType(dict(value))
