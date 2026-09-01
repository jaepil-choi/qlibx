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

    def inputs(self) -> Mapping[str, DatasetInput]:
        """Declare every aliased dataset read this Model performs. Empty by default.

        The alias is the author's own name for a read, and it is what `context.read(alias)` takes.
        Declaring nothing is legitimate: a Model may derive its values from memory alone.
        """
        return {}

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Every observation requirement available during invocation.

        Derived from `inputs()` rather than written separately, so a Model cannot declare one
        thing to preflight and read another at the callback.

        **A Model that overrides this instead still works**, and many do. That is the older shape —
        a hand-built tuple of `DataRequirement` — and a Model using it reads through
        `context.window.observations(...)` while leaving `reads` empty. Both paths resolve against
        the same window, so a tree part-way through the migration behaves identically either way.

        One alias becomes one requirement per declared field (`docs/issues/049`), so a model
        declaring one alias over three fields declares three requirements here.
        """
        return tuple(
            requirement
            for declaration in self.inputs().values()
            for requirement in requirements_for(declaration)
        )
