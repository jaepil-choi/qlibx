"""Opaque, portable Strategy-owned state values."""

from __future__ import annotations

import hashlib
import json
import math
from typing import TypeAlias

from qlibx.models import QlibxModel

StrategyStateValue: TypeAlias = (
    bool
    | int
    | float
    | str
    | list["StrategyStateValue"]
    | dict[str, "StrategyStateValue"]
    | None
)


class StrategyStateUpdate(QlibxModel):
    """Explicitly distinguish no update from updating the state to JSON null."""

    value: object = None


class StrategyStateSnapshot(QlibxModel):
    """One Strategy state value at an explicit run or invocation boundary."""

    strategy_id: str
    value: object = None


class StrategyStateJsonError(ValueError):
    """Raised when a Strategy state value is not strict portable JSON."""


def normalize_strategy_state(value: object) -> StrategyStateValue:
    """Return a detached strict-JSON copy without interpreting Strategy-owned keys."""

    normalized = _normalize(value, path="$state")
    # A canonical round trip proves the accepted graph is portable and detached.
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return json.loads(encoded)


def strategy_state_fingerprint(value: object) -> str:
    normalized = normalize_strategy_state(value)
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: object, *, path: str) -> StrategyStateValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StrategyStateJsonError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, list):
        return [_normalize(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        normalized: dict[str, StrategyStateValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrategyStateJsonError(f"{path} contains a non-string object key")
            normalized[key] = _normalize(item, path=f"{path}.{key}")
        return normalized
    raise StrategyStateJsonError(
        f"{path} contains non-JSON type {type(value).__name__}"
    )


__all__ = [
    "StrategyStateJsonError",
    "StrategyStateSnapshot",
    "StrategyStateUpdate",
    "StrategyStateValue",
    "normalize_strategy_state",
    "strategy_state_fingerprint",
]