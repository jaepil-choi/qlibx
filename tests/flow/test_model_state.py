from __future__ import annotations

import math

import pytest

from vqapr.domain.values import normalize_memory
from vqapr.flow.run_state import prepare_model_state


def test_prepared_memory_and_payload_are_detached_and_identity_bound() -> None:
    memory = {"count": 1, "recent": ["2024-03-05"]}

    prepared = prepare_model_state(memory, b"first")
    memory["count"] = 999
    memory["recent"].append("2024-03-06")

    assert prepared.memory == {"count": 1, "recent": ["2024-03-05"]}
    assert prepared.payload == b"first"
    assert prepare_model_state(prepared.memory, b"second").ref != prepared.ref


@pytest.mark.parametrize("value", [{1: "bad"}, ("tuple",), math.nan, math.inf])
def test_model_memory_rejects_values_outside_strict_json(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        normalize_memory(value)


def test_model_memory_rejects_cycles() -> None:
    value: list[object] = []
    value.append(value)

    with pytest.raises(ValueError, match="cycles"):
        normalize_memory(value)
