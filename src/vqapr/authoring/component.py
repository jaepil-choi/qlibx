"""What an author subclasses: the Component, the part/tool split, and the three roles here.

A Component is an object the engine calls back on an event, with that event's time. The roles
differ in what the callback is handed and what it returns -- values in, a dataset out for a
`DataModel`; an account and a decision for a `StrategyModel`; the committed book and a finding
for a `Compliance` rule -- and an `Exchange` is the fourth, declared in `exchange/venue.py`
because it also needs the venue's own vocabulary (owner ruling 2026-09-08, record `184`).

`Constraint` was the third role until record `208`: it projected a box for the strategy AND
observed the book, two members on two clocks. Design §7.1 made the projection a kit of pure
functions the strategy calls (`vqapr.portfolio.bounds`) and §7.2 kept the observation as its own
role, on the market clock, with its own parameters.

This is the top of the package: it imports every value the roles exchange and nothing imports it
back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from decimal import Decimal
from typing import BinaryIO, ClassVar

from vqapr.authoring.call import ComplianceCall, DataCall, StrategyCall
from vqapr.authoring.history import AccountHistoryInput
from vqapr.authoring.reads import DatasetInput, requirements_for
from vqapr.authoring.records import InvocationRecorder, TableSpec
from vqapr.authoring.result import ComplianceFinding, Hold, Rebalance
from vqapr.authoring.view import EconomicAccountView
from vqapr.data.requirements import DataRequirement
from vqapr.domain.shapes import Rows
from vqapr.domain.values import ModelMemory
from vqapr.domain.wiring import WIRING, Role, Wiring


class Component(ABC):
    """An object the engine calls back on an event, with that event's time.

    **This is the one thing the four authored kinds are** (owner ruling, 2026-09-08; the review in
    `docs/code-review/2026-09-08-four-readers-one-loop-and-the-missing-shapes.md`). A DataModel,
    a StrategyModel, a Compliance rule and an Exchange each *declare what they read* (`inputs()`),
    are *handed a bounded view of it at one instant* (their `Call`), *carry memory between
    callbacks* (`memory`), and *return one judgment* -- rows, a decision, a finding, fills. What
    differs between them is the event they answer and what their role is additionally handed:
    the account for a Strategy, the committed and marked account for a Compliance rule's
    `observe`, the order batch for an Exchange. That list is the whole difference, and it is
    stated on each role rather than here.

    **The author's base class, so it lives on the author's surface.** An engine-side `models/`
    package once held it while `DataModel` and `StrategyModel` were defined here without it, so the
    two authored kinds shared no ancestor and an author who wrote against this module got a class
    the loader could not run (`docs/issues/archive/036`). The observing role then stood outside
    the base for a reason that turned out to be wrong -- *"a constraint is a stateless predicate"*
    -- and copied `inputs()` and `requirements()` verbatim to get the same declaration. A rule
    such as *"out after three breaches"* needs to count, and counting is memory; the premise was
    the defect, not the copy.

    **Every role declares its reads here, in one place and one shape.** A first-time user once had
    to build a ten-row table of the ways authoring two roles differed; the owner ruled that
    *"the size of the current difference is itself the defect"*. `inputs()` is the one shape.

    `memory` is the small strict-JSON state a component carries between callbacks. The engine
    restores it before each callback and commits what the callback left, atomically with the
    callback's other effects; a fresh instance with its memory restored must decide the same. A
    DataModel that uses it becomes order-dependent (architecture 4.4); one that does not may be
    computed in any order. The engine relies on the same instance living for the whole run: it
    never builds one per callback.

    `Exchange` is the fourth role and joined at record `184`, but it is declared in
    `exchange/venue.py` rather than here: what a user subclasses is a shipped profile, not a
    blank surface -- `load_exchange` refuses a subclass that replaces `execute`, because the
    realism claim of a profile is its fill semantics. It is a Component in every other respect:
    called on the due event a callback minted, handed an `ExecutionCall`, carrying `memory` the
    run commits with that fill's account commit.
    """

    memory: ModelMemory = None

    ROLE: ClassVar[Role]
    """Which row of the wiring table this role is (design §4). Set by each role class; the table
    -- not the class -- says which clock it is called on and who receives its answer."""

    @classmethod
    def wiring(cls) -> Wiring:
        """This role's row of the table: its clock, what it is handed, who receives its answer."""
        return WIRING[cls.ROLE]

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this component performs. Empty by default.

        The alias is the author's own name for a read, and it is what `read(alias)` takes on the
        call. Declaring nothing is legitimate: a Model may derive its values from memory alone.

        **Evaluated before `memory` exists.** Registration and preflight call this on a fresh
        instance, before any `initial_model_memory` is applied or a snapshot restored, and the run
        refuses a model whose requirements then differ from the frozen ones. So the reads cannot
        depend on memory or on a run's per-model settings (`docs/issues/archive/065`): a family of
        settings that changes WHAT is read is a family of registered components.

        Declaring nothing is legitimate and is what the shipped `NoShort` rule does: a rule
        about a holding's sign opens no data. The loader used to require a non-empty
        `requirements()` from the observing role, which made the one shipped rule that needs no
        data the one shape it could not accept.
        """
        return {}

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Every observation requirement, derived from `inputs()` rather than written twice."""
        return tuple(
            requirement
            for declaration in self.inputs().values()
            for requirement in requirements_for(declaration)
        )


class Part(Component):
    """A Component that declares its own clock -- one per run (design §4.3).

    **A part is a tool plus a clock.** A run holds exactly one part, and the part's agenda
    (`RunDefinition.agenda`, design §3.4) is the strategy clock the run is called on. What a part
    reads and remembers is what every Component reads and remembers; what makes it a part is that
    a run cannot be declared without naming it and its clock.
    """


class Tool(Component):
    """A Component that attaches to somebody else's clock (design §4.3).

    A tool declares no clock: the wiring table says which one it is called on -- today the
    market clock, for all three (`Exchange`, `Compliance`, and the `Accrual` place) -- and a run
    may declare several of one kind (compliance rules) or none.
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
    def observe(self, call: ComplianceCall, account: EconomicAccountView) -> ComplianceFinding:
        """Measure the committed, marked account at the market-clock instant it was marked at.

        `account.weight(instrument_id)` is the derivation a weight-based rule wants; `positions`
        and `values` are there for a rule that asks about quantity or about money. `call` carries
        the rule's own declared reads as of that instant, and its `memory` was restored before
        this call and is committed after it, so a rule that counts can count.
        """
