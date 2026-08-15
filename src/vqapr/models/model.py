"""Common user-Model contract without runtime or storage authority."""

from __future__ import annotations

from abc import ABC

from vqapr.data.requirements import DataRequirement
from vqapr.models.memory import ModelMemory


class Model(ABC):  # noqa: B024 - concrete Model roles add abstract callbacks
    """Shared declaration and portable memory surface for user Models."""

    memory: ModelMemory = None

    def requirements(self) -> tuple[DataRequirement, ...]:
        """Declare every observation requirement available during invocation."""
        return ()
