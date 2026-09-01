"""Common user-Model contract without runtime or storage authority."""

from __future__ import annotations

from abc import ABC
from collections.abc import Mapping

from vqapr.authoring import DatasetInput
from vqapr.data.requirements import DataRequirement
from vqapr.models.calls import requirements_for
from vqapr.models.memory import ModelMemory


class Model(ABC):  # noqa: B024 - concrete Model roles add abstract callbacks
    """Shared declaration and portable memory surface for user Models.

    **Both roles declare their reads here, in one place and one shape.** `docs/issues/036` records
    what it cost not to: a first-time user had to build a ten-row table of the differences between
    authoring a DataModel and authoring a StrategyModel, and the owner ruled that *"the size of the
    current difference is itself the defect"*. `inputs()` is that one shape.
    """

    memory: ModelMemory = None

    component_id: str | None = None
    """Who this component is, stamped by the loader rather than written by the author.

    It reaches a `DataRequirement` as its `consumer_id`, which is how an access record says which
    component read what. An author asked to supply it could supply it wrong, and it is a value the
    loader already holds — asking is both risky and redundant. The scaffold hoisting it into a
    `MODEL_ID` constant, so the author would only mistype it once, was the symptom.
    """

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this Model performs. Empty by default.

        The alias is the author's own name for a read, and it is what `context.read(alias)` takes.
        Declaring nothing is legitimate: a Model may derive its values from memory alone.
        """
        return {}

    def declared_reads(self) -> dict[str, tuple[DataRequirement, ...]]:
        """The engine requirements each declared alias resolves to, keyed by alias.

        The Flow hands this to the context, which is what lets `read(alias)` serve it. One alias
        is one requirement today and becomes one per field when `docs/issues/049` lands; the tuple
        is already that shape, so nothing here changes then.
        """
        return requirements_for(self.component_id or type(self).__name__, self.inputs())

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Every observation requirement available during invocation.

        Derived from `inputs()` rather than written separately, so a Model cannot declare one
        thing to preflight and read another at the callback.

        **A Model that overrides this instead still works**, and many do. That is the older shape —
        a hand-built tuple of `DataRequirement` — and a Model using it reads through
        `context.window.observations(...)` while leaving `reads` empty. Both paths resolve against
        the same window, so a tree part-way through the migration behaves identically either way.
        """
        return tuple(
            requirement
            for group in self.declared_reads().values()
            for requirement in group
        )
