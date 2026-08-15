from __future__ import annotations

import math

import pytest

from vqapr.flow.model_state import InMemoryModelStateStore
from vqapr.models.memory import normalize_memory


def test_committed_memory_is_detached_from_the_strategy_object() -> None:
    store = InMemoryModelStateStore()
    memory = {"count": 1, "recent": ["2024-03-05"]}

    ref = store.commit(memory)
    memory["count"] = 999
    memory["recent"].append("2024-03-06")

    assert store.load(ref) == {"count": 1, "recent": ["2024-03-05"]}


@pytest.mark.parametrize("value", [{1: "bad"}, ("tuple",), math.nan, math.inf])
def test_model_memory_rejects_values_outside_strict_json(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        normalize_memory(value)


def test_model_memory_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)

    with pytest.raises(ValueError, match="cycles"):
        normalize_memory(value)
