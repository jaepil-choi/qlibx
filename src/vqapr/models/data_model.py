"""DataModel extension contract: PIT data in, reusable value rows out."""

from __future__ import annotations

from abc import abstractmethod

from vqapr.domain.rows import Rows
from vqapr.models.contexts import DataModelContext
from vqapr.models.model import Model


class DataModel(Model):
    @abstractmethod
    def compute(self, context: DataModelContext) -> Rows:
        """Compute semantic rows for one frozen evaluation time."""
