"""What you hold is not always what you are exposed to.

Hold a fund and you are exposed to what the fund holds. Hold a stock and you are exposed to that
stock. Both are the same statement with a different matrix, and this module is that matrix:

    exposure = L @ holdings

where a column is something you can buy and a row is something you end up exposed to. A stock's
column is the identity; a fund's column is its constituent weights. Nothing here knows what an
exchange-traded fund is, and nothing here should: the same mapping covers depositary receipts,
index futures, and a fund of funds, and a package that special-cased one vehicle would have to
special-case the next.

**This measures and never decides.** It reports the exposure a book implies. Choosing what to hold,
how large a passive sleeve should be, or whether a vehicle is worth its tracking error is the
strategy's economic judgement, and canon is explicit that the package never expands a holding into
its constituents on its own — a strategy calls this function or no look-through happens.

Both panels arrive as arguments. There is no discovery path, no ticker convention and no default
composition, so an instrument the caller did not describe is held outright rather than expanded.
That is canon's rule and not a shortcut: the package cannot know a holding is a vehicle, and
guessing from a ticker would be the auto-expansion canon forbids. Describing a vehicle with an
empty constituent mapping *is* refused, because that is a caller naming something a vehicle and
then declining to say what is in it.

Only one level is resolved. A vehicle whose constituents are themselves vehicles needs its own
matrix, which is the caller's economic definition to make.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

__all__ = ["InstrumentExposure", "look_through"]


@dataclass(frozen=True, slots=True)
class InstrumentExposure:
    """Where one instrument's exposure came from."""

    instrument_id: str
    direct: Decimal
    """Held outright."""

    indirect: Decimal
    """Held through a vehicle, summed across every vehicle that carries it."""

    total: Decimal
    """``direct + indirect``. What the book is actually exposed to."""

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        for name in ("direct", "indirect", "total"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")


def look_through(
    holdings: Mapping[str, Decimal],
    *,
    composition: Mapping[str, Mapping[str, Decimal]],
) -> dict[str, InstrumentExposure]:
    """Map a physical book onto the exposure it implies.

    ``holdings`` is what is held, by instrument. ``composition`` describes the vehicles among
    them, each as its own constituent weights; an instrument absent from it is held outright and
    contributes its own weight directly.

    The split between direct and indirect is kept rather than collapsed, because it is the part a
    reader cannot recover afterwards: a name at three percent total reads very differently when it
    arrived as three percent outright than when it arrived through a vehicle, and only the first is
    a position a strategy chose per name.

    A vehicle is not itself an exposure. Its column carries its constituents and its own row is
    absent, because it is the means and not the thing exposed to. A strategy that wants a vehicle
    treated as an exposure in its own right is describing a different matrix, which is its own
    economic definition to make.
    """
    if not isinstance(holdings, Mapping):
        raise TypeError("holdings must be a mapping of instrument to Decimal")
    if not isinstance(composition, Mapping):
        raise TypeError("composition must be a mapping of vehicle to constituent weights")

    checked: dict[str, Decimal] = {}
    for instrument, weight in holdings.items():
        if not isinstance(instrument, str) or not instrument:
            raise ValueError("holdings has a non-string instrument identifier")
        if not isinstance(weight, Decimal):
            raise TypeError(
                f"holdings[{instrument!r}] must be a Decimal; got {type(weight).__name__}"
            )
        if not weight.is_finite():
            raise ValueError(f"holdings[{instrument!r}] must be finite")
        checked[instrument] = weight

    vehicles: dict[str, dict[str, Decimal]] = {}
    for vehicle, constituents in composition.items():
        if not isinstance(vehicle, str) or not vehicle:
            raise ValueError("composition has a non-string vehicle identifier")
        if not isinstance(constituents, Mapping) or not constituents:
            raise ValueError(f"composition[{vehicle!r}] must be a non-empty mapping")
        entry: dict[str, Decimal] = {}
        for instrument, weight in constituents.items():
            if not isinstance(instrument, str) or not instrument:
                raise ValueError(f"composition[{vehicle!r}] has a non-string constituent")
            if not isinstance(weight, Decimal):
                raise TypeError(
                    f"composition[{vehicle!r}][{instrument!r}] must be a Decimal; "
                    f"got {type(weight).__name__}"
                )
            if not weight.is_finite():
                raise ValueError(f"composition[{vehicle!r}][{instrument!r}] must be finite")
            entry[instrument] = weight
        vehicles[vehicle] = entry

    direct: dict[str, Decimal] = {}
    indirect: dict[str, Decimal] = {}
    for instrument, weight in checked.items():
        if instrument in vehicles:
            for constituent, share in vehicles[instrument].items():
                indirect[constituent] = indirect.get(constituent, Decimal(0)) + weight * share
        else:
            direct[instrument] = direct.get(instrument, Decimal(0)) + weight

    exposed: dict[str, InstrumentExposure] = {}
    for instrument in sorted(set(direct) | set(indirect)):
        held = direct.get(instrument, Decimal(0))
        through = indirect.get(instrument, Decimal(0))
        exposed[instrument] = InstrumentExposure(
            instrument_id=instrument,
            direct=held,
            indirect=through,
            total=held + through,
        )
    return exposed
