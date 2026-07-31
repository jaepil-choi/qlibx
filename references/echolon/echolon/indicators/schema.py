"""Pydantic schema + expansion helpers for the flat-dict indicator_list format.

Schema (runtime dict validated by IndicatorList):
    {
        "<indicator_name>": {"<param_name>": <scalar | list>, ...},
        ...
    }

Expansion rules per-param value:
    - scalar (int/float/str) → single value
    - list [a, b] where both are ints and b > a → inclusive integer range [a, b]
    - list [v1, v2, v3, ...] (len != 2, or contains floats) → explicit values
    - list of length 1 → single-element explicit

Multi-param Cartesian: when multiple params are lists (after expansion),
compute cross product of all expanded sequences.
"""
from __future__ import annotations

import itertools
from typing import Any, Dict, List, Union

from pydantic import BaseModel, RootModel, field_validator, model_validator


ParamValue = Union[int, float, str, List[Union[int, float]]]


class _IndicatorEntry(RootModel[Dict[str, ParamValue]]):
    """One indicator's params. Empty dict = use library defaults."""


class IndicatorList(RootModel[Dict[str, _IndicatorEntry]]):
    """The full flat-dict indicator_list."""

    @field_validator("root")
    @classmethod
    def _reject_empty(cls, v):
        if not v:
            raise ValueError("indicator_list must contain at least one indicator")
        return v

    @model_validator(mode="after")
    def _validate_against_catalog(self):
        """Check every name + param against the echolon indicator catalog.

        Deferred-import to avoid a circular import during catalog hydration
        (catalog imports from ``echolon.indicators.calculators.*`` which doesn't
        touch this module, but we keep the import lazy as a defensive move).
        """
        from echolon.indicators import catalog as _catalog

        raw: Dict[str, Any] = {
            name: (entry.root if isinstance(entry, _IndicatorEntry) else entry)
            for name, entry in self.root.items()
        }
        errors = _catalog.validate(raw)
        if errors:
            lines = [
                f"[{e['code']}] {e['field']}: {e['message']}"
                for e in errors
            ]
            raise ValueError("; ".join(lines))
        return self


def _is_integer_range(values: list) -> bool:
    """Return True iff [a, b] where both are ints and b > a (inclusive range convention)."""
    return (
        len(values) == 2
        and isinstance(values[0], int)
        and isinstance(values[1], int)
        and not isinstance(values[0], bool)  # bools are ints in Python; reject
        and not isinstance(values[1], bool)
        and values[1] >= values[0]
    )


def expand_param(value: ParamValue) -> list:
    """Expand a single param value to a list of concrete values per the schema rules."""
    if not isinstance(value, list):
        return [value]
    if _is_integer_range(value):
        return list(range(value[0], value[1] + 1))
    return list(value)


def expand_params_spec(spec: Dict[str, ParamValue]) -> List[Dict[str, Any]]:
    """Expand a per-indicator params dict into all combinations (Cartesian product).

    Example:
        {"period": [15, 17], "stddev": [1.5, 2.5]}
        → [
            {"period": 15, "stddev": 1.5},
            {"period": 15, "stddev": 2.5},
            {"period": 16, "stddev": 1.5},
            ...
        ]
    """
    if not spec:
        return [{}]  # single combination with no params (use defaults)

    names = list(spec.keys())
    expanded = [expand_param(spec[name]) for name in names]
    return [dict(zip(names, combo)) for combo in itertools.product(*expanded)]
