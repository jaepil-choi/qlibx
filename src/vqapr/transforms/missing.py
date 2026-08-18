"""What to do about a name with no value — and what never to do.

There is no `fill_missing` here, and there will not be one. Filling a gap with zero is not a
neutral technical convenience: it says the name had no exposure, no signal, no return, which is a
claim about the world that the data did not make. If a researcher wants to assert that, they should
have to write it themselves and see themselves writing it.

That leaves exactly two honest moves. Either the name is not in the cross-section for this date, or
its absence is a problem and the computation should stop and say so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

__all__ = ["drop_missing", "require_complete"]


def drop_missing(values: Mapping[str, Decimal | None]) -> dict[str, Decimal]:
    """Remove names with no value, keeping the rest exactly as they are.

    The result is a smaller cross-section, not a padded one. Every operation downstream then works
    on names that genuinely had a value on this date, and the coverage of the result is visible in
    its length rather than hidden behind zeros.
    """
    if not isinstance(values, Mapping):
        raise TypeError("drop_missing takes a mapping of instrument to Decimal or None")
    kept: dict[str, Decimal] = {}
    for instrument, value in values.items():
        if not isinstance(instrument, str) or not instrument:
            raise ValueError("drop_missing received a non-string instrument identifier")
        if value is None:
            continue
        if not isinstance(value, Decimal):
            raise TypeError(
                f"drop_missing[{instrument!r}] must be a Decimal or None; "
                f"got {type(value).__name__}"
            )
        if not value.is_finite():
            raise ValueError(f"drop_missing[{instrument!r}] must be finite")
        kept[instrument] = value
    return kept


def require_complete(
    values: Mapping[str, Decimal | None], *, instruments: Iterable[str]
) -> dict[str, Decimal]:
    """Return the cross-section only if every named instrument has a value.

    For the computations where a partial cross-section is not a smaller answer but a wrong one — a
    benchmark whose weights must sum, an exposure matrix that must span its columns — this refuses
    and names what is missing, rather than proceeding on whatever happened to be present.
    """
    if not isinstance(values, Mapping):
        raise TypeError("require_complete takes a mapping of instrument to Decimal or None")
    required = tuple(instruments)
    if not required:
        raise ValueError("require_complete needs at least one required instrument")
    if any(not isinstance(name, str) or not name for name in required):
        raise ValueError("required instruments must be non-empty strings")

    present = drop_missing(values)
    absent = sorted(set(required) - set(present))
    if absent:
        raise ValueError(f"required instruments have no value: {absent}")
    return {instrument: present[instrument] for instrument in required}
