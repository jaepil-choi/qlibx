"""Portable, detached Model memory used at the callback commit boundary."""

from __future__ import annotations

import math

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
