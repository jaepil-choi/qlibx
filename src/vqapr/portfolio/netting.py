"""Decision-time diagnostics — measurement that never decides.

When several members are combined, the interesting number is not the result but what happened on
the way there: one member wanted a name long, another wanted it short, and part of each cancelled.
That offset is invisible in the final weight, so it has to be measured where it happens.

**This module measures and never decides.** It takes member weights and reports what combining them
implies; it does not choose the combination rule, does not scale to a budget, and does not return
anything a Strategy could use as its allocation without deciding for itself. Implementation record
010 prohibits a package-supplied ensemble combination helper, and that prohibition stands: equal
weighting, IC weighting and risk parity remain the researcher's economic choice. Reporting the
arithmetic of an offset is not making that choice.

Everything here is pure, and every number is in **weight space**. A published allocation carries
weight economics only, so an offset expressed in quantities would have nowhere to live, and reading
a recorded quantity as if it were a fill is what PRD section 9.4 forbids.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TickerNetting:
    """What combining the members implied for one instrument."""

    instrument_id: str
    long_weight: Decimal
    """Sum of the positive member weights."""

    short_weight: Decimal
    """Sum of the negative member weights, carried negative."""

    offset_weight: Decimal
    """How much of each side the other cancelled.

    ``min(long, |short|)``, so it is zero whenever the members agree on direction and positive only
    where they genuinely disagreed. This is the quantity UC-ENSEMBLE-001 requires to be confirmable,
    and it cannot be recovered from the net alone: a net of zero can mean nobody held the name, or
    that two members cancelled exactly.
    """

    net_weight: Decimal
    """``long + short``. What survives the disagreement."""

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        for name in ("long_weight", "short_weight", "offset_weight", "net_weight"):
            value = getattr(self, name)
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")


def net_members(
    members: Sequence[Mapping[str, Decimal]], *, instruments: Sequence[str] | None = None
) -> dict[str, TickerNetting]:
    """Measure, per instrument, what combining the member weights implies.

    ``members`` are the members' own weights, each mapping instrument to a signed weight.
    Instruments absent from a member are treated as that member holding nothing, which is what
    absence means in a published allocation panel.

    The result is a measurement, not an allocation. It reports the long side, the short side, how
    much they cancelled and what survived; choosing what to do with that is the Strategy's.
    """
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
        raise TypeError("members must be a sequence of weight mappings")
    if len(members) < 2:
        raise ValueError(
            "netting needs at least two members; with one member there is nothing to offset"
        )

    checked: list[dict[str, Decimal]] = []
    for index, member in enumerate(members):
        if not isinstance(member, Mapping):
            raise TypeError(f"members[{index}] must be a mapping of instrument to Decimal")
        entry: dict[str, Decimal] = {}
        for instrument, weight in member.items():
            if not isinstance(instrument, str) or not instrument:
                raise ValueError(f"members[{index}] has a non-string instrument identifier")
            if not isinstance(weight, Decimal):
                raise TypeError(
                    f"members[{index}][{instrument!r}] must be a Decimal; "
                    f"got {type(weight).__name__}"
                )
            if not weight.is_finite():
                raise ValueError(f"members[{index}][{instrument!r}] must be finite")
            entry[instrument] = weight
        checked.append(entry)

    if instruments is None:
        universe = sorted({instrument for member in checked for instrument in member})
    else:
        universe = sorted(instruments)
        if any(not isinstance(name, str) or not name for name in universe):
            raise ValueError("instruments must be non-empty strings")

    measured: dict[str, TickerNetting] = {}
    for instrument in universe:
        weights = [member.get(instrument, Decimal(0)) for member in checked]
        long_side = sum((w for w in weights if w > 0), Decimal(0))
        short_side = sum((w for w in weights if w < 0), Decimal(0))
        measured[instrument] = TickerNetting(
            instrument_id=instrument,
            long_weight=long_side,
            short_weight=short_side,
            offset_weight=min(long_side, -short_side),
            net_weight=long_side + short_side,
        )
    return measured


__all__ = ["TickerNetting", "net_members"]
