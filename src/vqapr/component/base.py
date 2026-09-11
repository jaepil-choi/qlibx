"""What every extension point is: the `Component`, and the part/tool split.

A Component is an object the engine calls back at an event, with that event's time. Every role --
DataModel, StrategyModel, Exchange, Compliance -- declares what it reads (`inputs()`), is handed a
bounded view of it at one instant (its call), carries strict-JSON `memory` between callbacks, and
returns one judgment. What differs between the roles is when they are called and who receives the
answer, and the wiring table (`domain/wiring.py`) holds both; a role class names its row with
`ROLE`.

**A part is a tool plus a clock.** A `Part` declares its own clock, one per run: DataModel,
StrategyModel. A `Tool` attaches to somebody else's clock: Exchange, Compliance, and the Accrual
place. Each role lives in its own module beside this one, its base apart from any shipped
implementation.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Mapping
from typing import ClassVar

from vqapr.component.reads import DatasetInput, requirements_for
from vqapr.data.requirement import DataRequirement
from vqapr.domain.memory import ModelMemory
from vqapr.domain.wiring import WIRING, Role, Wiring

__all__ = [
    "Component",
    "Part",
    "Tool",
]


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
    `exchange/base.py` rather than here: what a user subclasses is a shipped profile, not a
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
