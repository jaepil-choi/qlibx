"""Model invocation contexts; capability absence is an intentional boundary."""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.data.windows import ModelWindow


@dataclass(frozen=True, slots=True)
class DataModelContext:
    window: ModelWindow

    def __post_init__(self) -> None:
        if not isinstance(self.window, ModelWindow):
            raise TypeError("window must be a ModelWindow")
