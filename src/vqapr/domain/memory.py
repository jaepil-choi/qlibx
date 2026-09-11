"""A component's memory, and the envelope its committed state is hashed over.

`ModelMemory` is strict JSON. `normalize_memory` refuses non-finite floats, non-string keys and
cycles, and returns a detached deep copy, so a later in-place change cannot alter a past snapshot.
`opening_memory` is what a first callback finds: the declared value, or `{}`. `prepare_model_state`
frames a memory with the optional payload into one envelope and hashes it -- no clock, no account,
no IO. The engine takes the reference of what a callback committed, and a run declaration derives
the reference of the memory it starts with.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from vqapr.domain.identifiers import ModelStateRef

__all__ = [
    "ModelMemory",
    "PreparedModelState",
    "normalize_memory",
    "opening_memory",
    "prepare_model_state",
]


type ModelMemory = bool | int | float | str | list["ModelMemory"] | dict[str, "ModelMemory"] | None


def normalize_memory(value: object) -> ModelMemory:
    """Validate strict JSON memory and return a detached recursive copy."""

    active: set[int] = set()

    def visit(item: object) -> ModelMemory:
        if item is None or isinstance(item, (bool, str)):
            return item
        if isinstance(item, int):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Model memory floats must be finite")
            return item
        if isinstance(item, list):
            identity = id(item)
            if identity in active:
                raise ValueError("Model memory must not contain cycles")
            active.add(identity)
            try:
                return [visit(child) for child in item]
            finally:
                active.remove(identity)
        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise ValueError("Model memory must not contain cycles")
            if any(not isinstance(key, str) for key in item):
                raise TypeError("Model memory object keys must be strings")
            active.add(identity)
            try:
                return {key: visit(child) for key, child in item.items()}
            finally:
                active.remove(identity)
        raise TypeError(f"Model memory must contain strict JSON values; got {type(item).__name__}")

    return visit(value)


def opening_memory(value: object) -> ModelMemory:
    """The memory a model finds on its first callback: `value` normalized, and `{}` for `None`.

    The authoring reference promises `self.memory` is a mapping a callback can `setdefault` on
    from session one. An undeclared opening memory was `None`, so the documented example raised
    on the first callback of every run (`docs/issues/089`). "Nothing declared" and "declared
    `null`" are one opening state, and it is the empty mapping; any other strict-JSON value a
    run declares is kept as declared.
    """
    normalized = normalize_memory(value)
    return {} if normalized is None else normalized


@dataclass(frozen=True, slots=True)
class PreparedModelState:
    """A detached state candidate with no visibility until its root is published."""

    ref: ModelStateRef
    memory: ModelMemory
    payload: bytes


def prepare_model_state(memory: object, payload: bytes) -> PreparedModelState:
    """Detach one exact memory/payload envelope without making it visible."""
    normalized = normalize_memory(memory)
    memory_bytes = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    envelope = (
        len(memory_bytes).to_bytes(8, "big")
        + memory_bytes
        + len(payload).to_bytes(8, "big")
        + payload
    )
    return PreparedModelState(
        ref=ModelStateRef(hashlib.sha256(envelope).hexdigest()),
        memory=normalized,
        payload=bytes(payload),
    )
