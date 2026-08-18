"""Turning a signal into weights, and separately, matching a declared budget.

Every function here is pure: same input, same output, no clock, no account, no I/O.

**The sign always comes from the input; only the source of the magnitude differs.**
``signal_weight`` sizes by ``|signal|``, ``equal_weight`` sizes everything the same, and
``proportional_weight`` sizes by a supplied panel. All three return weights normalised to
**gross one**. That is a unit, not a budget: without it the output is not a weight at all, just
the signal again.

The two halves guarantee different things, and they cannot both be exact when a division does not
terminate:

* **Sizing keeps the ratios exact.** ``equal_weight`` really does give equal weights; three names
  each get ``1/3``, whose gross is one only to the precision a Decimal can hold.
* **``rescale`` keeps the declared total exact.** Asking for a long side of one gets exactly one,
  with the rounding residual settled onto the largest member of that side. PRD 5.5 treats a
  declared budget that does not match the actual weights as a failure, so the declaration wins here.

Matching a budget is a separate call, because PRD 5.5 forbids the sizing operation from deciding it:

    fixed budget      rescale(w, long=1, short=-1)   fills the declared budget, concentrating
                                                     into whatever names the signal picked
    flexible budget   w                              left at unit gross, or narrowed by the
                                                     Strategy's own rule

A sizing function that quietly normalised to a declared budget would turn flexible into fixed
without saying so, and the two are economically different answers. Keeping them in separate calls
means the strategy's own source code shows which one it chose.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

Weights = dict[str, Decimal]


class WeightingRefusal(ValueError):
    """A typed refusal naming the input that cannot be turned into weights."""


def _panel(values: Mapping[str, Decimal], *, name: str) -> dict[str, Decimal]:
    if not isinstance(values, Mapping) or not values:
        raise WeightingRefusal(f"{name} must be a non-empty mapping of instrument to Decimal")
    checked: dict[str, Decimal] = {}
    for instrument in sorted(values):
        value = values[instrument]
        if not isinstance(instrument, str) or not instrument:
            raise WeightingRefusal(f"{name} has a non-string instrument identifier")
        if not isinstance(value, Decimal):
            raise WeightingRefusal(
                f"{name}[{instrument!r}] must be a Decimal; got {type(value).__name__}"
            )
        if not value.is_finite():
            raise WeightingRefusal(f"{name}[{instrument!r}] must be finite")
        checked[instrument] = value
    return checked


def _settle(weights: Weights, members: list[str], target: Decimal) -> None:
    """Place the division residual so the side reaches its target exactly.

    Dividing three ways leaves ``0.999...``, which would make the function report a total it did not
    produce. PRD 5.5 treats a declared total that does not match the actual weights as a failure, so
    the shortfall is settled rather than reported away.

    It lands on the **largest** member of that side, where it is the smallest relative distortion,
    with ties broken by instrument name so the result is order independent.
    """
    if not members:
        return
    total = sum((weights[name] for name in members), Decimal(0))
    residual = target - total
    if residual == 0:
        return
    anchor = max(members, key=lambda name: (abs(weights[name]), name))
    weights[anchor] += residual


def _normalise(sized: Mapping[str, Decimal], *, name: str) -> Weights:
    """Scale to gross one, keeping every sign exactly as supplied."""
    gross = sum((abs(value) for value in sized.values()), Decimal(0))
    if gross == 0:
        raise WeightingRefusal(
            f"{name} carries no non-zero entry, so there is nothing to weight; "
            "an empty book is a decision the Strategy has to make explicitly"
        )
    return {instrument: value / gross for instrument, value in sized.items()}


def signal_weight(signal: Mapping[str, Decimal]) -> Weights:
    """Size each position by the strength of its own signal.

    A signal twice as strong gets twice the weight. Zero-signal names are carried at zero rather
    than dropped, so the caller can still see they were in the universe.
    """
    checked = _panel(signal, name="signal")
    return _normalise(checked, name="signal")


def equal_weight(signal: Mapping[str, Decimal]) -> Weights:
    """Size every selected position the same, taking only the direction from the signal.

    Names with a zero signal are not selected: equal weighting means equal among the ones you
    picked, and a zero signal is not a pick.
    """
    checked = _panel(signal, name="signal")
    sized = {
        instrument: (Decimal(0) if value == 0 else Decimal(1).copy_sign(value))
        for instrument, value in checked.items()
    }
    return _normalise(sized, name="signal")


def proportional_weight(signal: Mapping[str, Decimal], sizes: Mapping[str, Decimal]) -> Weights:
    """Size each position by a supplied magnitude panel, taking direction from the signal.

    ``sizes`` is a magnitude such as market capitalisation, so it must be positive. Its own sign is
    never consulted; mixing a negative size with a signal sign would make the direction ambiguous.
    """
    checked = _panel(signal, name="signal")
    magnitudes = _panel(sizes, name="sizes")

    missing = sorted(set(checked) - set(magnitudes))
    if missing:
        raise WeightingRefusal(f"sizes does not cover every signalled instrument: {missing}")
    for instrument in checked:
        if magnitudes[instrument] <= 0:
            raise WeightingRefusal(
                f"sizes[{instrument!r}] must be positive; a magnitude panel carries no direction"
            )

    sized = {
        instrument: magnitudes[instrument].copy_sign(value) if value != 0 else Decimal(0)
        for instrument, value in checked.items()
    }
    return _normalise(sized, name="signal")


def rescale(weights: Mapping[str, Decimal], *, long: Decimal, short: Decimal) -> Weights:
    """Match a declared budget by scaling each side independently.

    ``rescale(w, long=1, short=-1)`` is dollar neutral; ``rescale(w, long=1, short=0)`` is a
    fully-invested long-only book. Calling this is what makes a budget *fixed*: the declared amount
    is filled even from a weak signal, which concentrates the book into whichever names it picked.

    It matches, it never invents. Asking for a long side out of a book with no longs is refused,
    and so is asking for a zero short side out of a book that holds shorts — that is deleting
    positions, not rescaling them.
    """
    checked = _panel(weights, name="weights")
    for name, target in (("long", long), ("short", short)):
        if not isinstance(target, Decimal):
            raise WeightingRefusal(f"{name} must be a Decimal; got {type(target).__name__}")
        if not target.is_finite():
            raise WeightingRefusal(f"{name} must be finite")
    if long < 0:
        raise WeightingRefusal("long must not be negative; it is the size of the long side")
    if short > 0:
        raise WeightingRefusal("short must not be positive; it is the size of the short side")

    long_gross = sum((value for value in checked.values() if value > 0), Decimal(0))
    short_gross = sum((value for value in checked.values() if value < 0), Decimal(0))

    for side, gross, target in (
        ("long", long_gross, long),
        ("short", short_gross, short),
    ):
        if gross == 0 and target != 0:
            raise WeightingRefusal(
                f"cannot rescale to a {side} side of {target}: the book holds no {side} position"
            )
        if gross != 0 and target == 0:
            raise WeightingRefusal(
                f"cannot rescale the {side} side to zero: that removes positions rather than "
                "resizing them, so the Strategy has to drop them deliberately"
            )

    scaled: Weights = {}
    for instrument, value in checked.items():
        if value > 0:
            scaled[instrument] = value * long / long_gross
        elif value < 0:
            scaled[instrument] = value * short / short_gross
        else:
            scaled[instrument] = Decimal(0)

    _settle(scaled, [name for name, value in scaled.items() if value > 0], long)
    _settle(scaled, [name for name, value in scaled.items() if value < 0], short)
    return scaled


__all__ = [
    "WeightingRefusal",
    "equal_weight",
    "proportional_weight",
    "rescale",
    "signal_weight",
]
