"""Cross-sectional operations that are not already one-line Python or pandas expressions.

Only tie-aware Decimal ranking remains generic. Demeaning, z-scoring and clipping are clearer as
ordinary arithmetic in the model that chooses them. Named methodology belongs in its own module;
Fama-French reference-market breakpoints live in ``fama_french.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

__all__ = ["rank"]


def _checked(values: Mapping[str, Decimal], name: str) -> dict[str, Decimal]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} takes a mapping of instrument to Decimal")
    if not values:
        raise ValueError(f"{name} needs a non-empty cross-section")
    checked: dict[str, Decimal] = {}
    for instrument, value in values.items():
        if not isinstance(instrument, str) or not instrument:
            raise ValueError(f"{name} received a non-string instrument identifier")
        if not isinstance(value, Decimal):
            raise TypeError(f"{name}[{instrument!r}] must be a Decimal; got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"{name}[{instrument!r}] must be finite")
        checked[instrument] = value
    return checked


def rank(values: Mapping[str, Decimal], *, ascending: bool = True) -> dict[str, Decimal]:
    """Order the cross-section, sharing a rank between ties.

    Ties take the average of the positions they span, so a group of equal values cannot be broken
    by whatever order the mapping happened to arrive in. Ranks start at one.
    """
    checked = _checked(values, "rank")
    ordered = sorted(checked.items(), key=lambda item: (item[1], item[0]), reverse=not ascending)

    ranked: dict[str, Decimal] = {}
    position = 0
    while position < len(ordered):
        stop = position
        while stop + 1 < len(ordered) and ordered[stop + 1][1] == ordered[position][1]:
            stop += 1
        shared = Decimal(position + stop + 2) / 2
        for index in range(position, stop + 1):
            ranked[ordered[index][0]] = shared
        position = stop + 1
    return {instrument: ranked[instrument] for instrument in checked}
