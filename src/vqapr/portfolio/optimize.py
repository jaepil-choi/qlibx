"""Constrained allocation solved exactly, with no solver package.

Without a cost term, a turnover penalty or an exposure mapping, the problem in Architecture 5.3
collapses to a box projection onto a budget hyperplane::

    minimise  || w - desired ||^2
    subject to  sum(w) + c = 1,  l <= w <= u,  c in cash_range,  w_j = current_j for j frozen

Its solution is parameterised by a single multiplier: ``w_i = clip(desired_i - lam, l_i, u_i)``.
The clipped sum is piecewise affine in ``lam`` with breakpoints at ``desired_i - l_i`` and
``desired_i - u_i``, so sorting those ``2n`` values locates the bracketing segment and the
multiplier is solved **exactly in rational arithmetic**. There is no iteration, so there is no
precision budget to declare and no tolerance to tune.

Three rules keep the result exact rather than approximately exact:

* **Frozen names are never quantized.** They are emitted verbatim from ``current`` so frozen
  invariance holds bit for bit. Precision is constrained at the entrance instead: a frozen input
  finer than the canonical grid is refused.
* **Cash is the only residual sink.** Adding a rounding residual to an instrument could push it
  past a bound that the caller was promised would hold.
* **Every returned weight lands on the canonical grid**, so a later ``sum(w) + cash == 1`` check
  carries few enough significant digits to be exact in the caller's own context. The associativity
  problem does not shrink, it disappears.
"""

from __future__ import annotations

import decimal
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise

QUANTIZATION_EXPONENT = -12
"""The canonical grid every package-produced weight lands on (Architecture 5.3)."""

QUANTUM = Decimal(1).scaleb(QUANTIZATION_EXPONENT)

WORKING_PRECISION = 50
"""Precision for assembly inside this function only.

It deliberately does not reach the caller. The exact solve runs in ``Fraction`` and is context
independent; this only keeps intermediate assembly from rounding before the result is quantized.
"""

_ROUNDING = decimal.ROUND_HALF_EVEN


class OptimizeRefusal(ValueError):
    """A typed refusal that names what the caller supplied and why it cannot be honoured."""


@dataclass(frozen=True, slots=True)
class OptimizeResult:
    """The projected allocation plus the cash that closes the budget identity."""

    weights: Mapping[str, Decimal]
    cash: Decimal
    multiplier: Decimal
    """The solved multiplier, quantized onto the canonical grid for reporting.

    It is a diagnostic, not a recomputation handle: the exact lambda is rational, so recomputing
    ``clip(desired - multiplier, l, u)`` from this rounded value can disagree with ``weights``.
    """
    binding_lower: tuple[str, ...]
    binding_upper: tuple[str, ...]
    frozen_outside_box: tuple[str, ...] = ()
    """Frozen instruments whose untradable holding lies outside its declared box.

    A diagnostic, not a violation. The holding is a market fact the Strategy could not change, so
    the projection honours it and says so. Whether that constitutes a breach is monitoring's call,
    made against the committed account rather than against this intent.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", dict(self.weights))


def _decimal(value: object, *, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise OptimizeRefusal(f"{name} must be a Decimal; got {type(value).__name__}")
    if not value.is_finite():
        raise OptimizeRefusal(f"{name} must be finite")
    return value


def _on_grid(value: Decimal, *, name: str) -> Decimal:
    """Refuse an input finer than the canonical grid, naming it.

    Coarser is fine: a caller may declare a bound at any precision the grid can represent. Only a
    finer value is refused, because quantizing toward it could land outside the caller's own box
    while this function reported success.
    """
    _decimal(value, name=name)
    if value.as_tuple().exponent < QUANTIZATION_EXPONENT:
        raise OptimizeRefusal(
            f"{name} has exponent finer than the canonical grid {QUANTUM}; "
            "coarser bounds are accepted, finer ones are not"
        )
    return value


def _fraction(value: Decimal) -> Fraction:
    return Fraction(value)


def optimize(
    *,
    desired: Mapping[str, Decimal],
    current: Mapping[str, Decimal],
    lower: Mapping[str, Decimal],
    upper: Mapping[str, Decimal],
    frozen: frozenset[str] = frozenset(),
    cash_range: tuple[Decimal, Decimal],
) -> OptimizeResult:
    """Project ``desired`` onto the feasible set exactly.

    ``cash_range`` is expected to be inset from the intent ``Budget`` by the quantization budget,
    so a result accepted here cannot be refused a moment later at intent construction.
    """
    instruments = tuple(sorted(desired))
    if not instruments:
        raise OptimizeRefusal("desired must name at least one instrument")
    for name, mapping in (("lower", lower), ("upper", upper)):
        missing = sorted(set(instruments) - set(mapping))
        if missing:
            raise OptimizeRefusal(f"{name} bounds are missing instruments: {missing}")
    unknown = sorted(frozen - set(instruments))
    if unknown:
        raise OptimizeRefusal(f"frozen names absent from desired: {unknown}")

    cash_lower = _on_grid(cash_range[0], name="cash_range lower")
    cash_upper = _on_grid(cash_range[1], name="cash_range upper")
    if cash_lower > cash_upper:
        raise OptimizeRefusal("cash_range lower must not exceed cash_range upper")

    for instrument in instruments:
        _on_grid(lower[instrument], name=f"lower[{instrument!r}]")
        _on_grid(upper[instrument], name=f"upper[{instrument!r}]")
        if lower[instrument] > upper[instrument]:
            raise OptimizeRefusal(f"lower[{instrument!r}] exceeds upper[{instrument!r}]")
        _decimal(desired[instrument], name=f"desired[{instrument!r}]")

    frozen_weights: dict[str, Decimal] = {}
    outside_box: list[str] = []
    for instrument in sorted(frozen):
        if instrument not in current:
            raise OptimizeRefusal(f"frozen instrument {instrument!r} is absent from current")
        # Guarded on entry, emitted verbatim on exit: the value itself is never rounded, so frozen
        # invariance is exact rather than approximate.
        held_weight = _on_grid(current[instrument], name=f"current[{instrument!r}]")
        # A frozen holding is a market fact the Strategy read, not a compliance rule (Architecture
        # 5.3). Projection is best effort: it works around what it cannot trade rather than refusing
        # to produce an allocation at all. A holding outside its declared box is reported as a
        # diagnostic, never raised -- refusing here would turn "could not trade" into "violated a
        # constraint", which is exactly the conflation canon forbids. Monitoring is the objective
        # judge, and it reads the committed account rather than this projection.
        if not lower[instrument] <= held_weight <= upper[instrument]:
            outside_box.append(instrument)
        frozen_weights[instrument] = held_weight

    free = tuple(name for name in instruments if name not in frozen)
    held = sum((_fraction(value) for value in frozen_weights.values()), Fraction(0))

    # The free block must absorb whatever the budget identity leaves after frozen holdings and a
    # cash choice inside the declared range.
    band_low = Fraction(1) - held - _fraction(cash_upper)
    band_high = Fraction(1) - held - _fraction(cash_lower)

    reach_low = sum((_fraction(lower[name]) for name in free), Fraction(0))
    reach_high = sum((_fraction(upper[name]) for name in free), Fraction(0))
    if reach_high < band_low or reach_low > band_high:
        raise OptimizeRefusal(
            "infeasible: the free block can reach "
            f"[{reach_low}, {reach_high}] but the budget requires [{band_low}, {band_high}]"
        )

    multiplier = _solve_multiplier(
        free=free,
        desired=desired,
        lower=lower,
        upper=upper,
        band_low=band_low,
        band_high=band_high,
    )

    with decimal.localcontext() as context:
        context.prec = WORKING_PRECISION
        weights: dict[str, Decimal] = {}
        binding_lower: list[str] = []
        binding_upper: list[str] = []
        free_total = Decimal(0)
        for name in free:
            exact = _fraction(desired[name]) - multiplier
            low = _fraction(lower[name])
            high = _fraction(upper[name])
            if exact <= low:
                value = lower[name]
                binding_lower.append(name)
            elif exact >= high:
                value = upper[name]
                binding_upper.append(name)
            else:
                value = Decimal(exact.numerator) / Decimal(exact.denominator)
            quantized = value.quantize(QUANTUM, rounding=_ROUNDING)
            weights[name] = quantized
            free_total += quantized
        frozen_total = sum(frozen_weights.values(), Decimal(0))
        cash = (Decimal(1) - frozen_total - free_total).quantize(QUANTUM, rounding=_ROUNDING)
        # Converting the exact multiplier belongs inside the working precision too: quantizing it
        # to the grid needs a twelve-digit coefficient, which a caller running at a tighter
        # precision could not represent, turning a valid answer into a raw arithmetic error.
        resolved = (Decimal(multiplier.numerator) / Decimal(multiplier.denominator)).quantize(
            QUANTUM, rounding=_ROUNDING
        )

    if not cash_lower <= cash <= cash_upper:
        cash, repaired = _absorb_grid_residual(
            cash=cash,
            cash_lower=cash_lower,
            cash_upper=cash_upper,
            weights=weights,
            free=free,
            lower=lower,
            upper=upper,
            binding_lower=binding_lower,
            binding_upper=binding_upper,
        )
        if not repaired:
            raise OptimizeRefusal(
                f"cash {cash} falls outside the declared range [{cash_lower}, {cash_upper}]"
            )

    weights.update(frozen_weights)
    return OptimizeResult(
        weights={name: weights[name] for name in instruments},
        cash=cash,
        frozen_outside_box=tuple(outside_box),
        multiplier=resolved,
        binding_lower=tuple(binding_lower),
        binding_upper=tuple(binding_upper),
    )


def _absorb_grid_residual(
    *,
    cash: Decimal,
    cash_lower: Decimal,
    cash_upper: Decimal,
    weights: dict[str, Decimal],
    free: tuple[str, ...],
    lower: Mapping[str, Decimal],
    upper: Mapping[str, Decimal],
    binding_lower: list[str],
    binding_upper: list[str],
) -> tuple[Decimal, bool]:
    """Move a sub-quantum rounding residual out of cash and back into an interior weight.

    The exact optimum satisfies ``cash_range`` by construction -- the feasibility check established
    that before the solve. Quantization is this function's own artifact, so a result that lands a
    few multiples of the grid outside the declared range describes a problem we made infeasible,
    not one the caller posed. Refusing there would hand back a false refusal on a solvable problem,
    which is exactly what a caller passing the natural ``cash_range=(0, 1)`` would hit whenever the
    exact answer is ``cash = 0``.

    The residual is moved into a single **interior** free weight, never one already resting on a
    bound, so the box every caller was promised still holds and the reported binding sets stay
    accurate. ``sum(w) + cash`` stays exactly one because the same amount leaves one side and
    arrives at the other. Selection is by sorted instrument order, so the repair is permutation
    invariant like the solve it corrects.
    """
    budget = QUANTUM * max(len(free), 1)
    if cash < cash_lower:
        shortfall = cash_lower - cash

        # Cash is short, so a weight must give some back: it needs slack above its own floor.
        def slack(name: str) -> Decimal:
            return weights[name] - lower[name]

        direction = Decimal(-1)
        target = cash_lower
    else:
        shortfall = cash - cash_upper

        # Cash is over, so a weight must take some on: it needs headroom below its own ceiling.
        def slack(name: str) -> Decimal:
            return upper[name] - weights[name]

        direction = Decimal(1)
        target = cash_upper

    if shortfall > budget:
        return cash, False

    resting = set(binding_lower) | set(binding_upper)
    for name in sorted(free):
        if name in resting or slack(name) < shortfall:
            continue
        weights[name] += direction * shortfall
        return target, True
    return cash, False


def _clipped_sum(
    lam: Fraction,
    free: tuple[str, ...],
    desired: Mapping[str, Decimal],
    lower: Mapping[str, Decimal],
    upper: Mapping[str, Decimal],
) -> Fraction:
    total = Fraction(0)
    for name in free:
        value = _fraction(desired[name]) - lam
        low = _fraction(lower[name])
        high = _fraction(upper[name])
        total += low if value <= low else high if value >= high else value
    return total


def _solve_multiplier(
    *,
    free: tuple[str, ...],
    desired: Mapping[str, Decimal],
    lower: Mapping[str, Decimal],
    upper: Mapping[str, Decimal],
    band_low: Fraction,
    band_high: Fraction,
) -> Fraction:
    """Return the exact multiplier placing the clipped free sum inside the budget band.

    ``lam = 0`` is preferred whenever it is feasible, because the unclipped projection is then the
    true minimiser and any other multiplier would move weights away from ``desired`` for nothing.
    """
    if not free:
        # Nothing is free, so the multiplier is unused; the frozen block alone must satisfy the
        # band, which the caller-side feasibility check has already established.
        return Fraction(0)

    zero = _clipped_sum(Fraction(0), free, desired, lower, upper)
    if band_low <= zero <= band_high:
        return Fraction(0)

    # The clipped sum is non-increasing in lam, so the feasible point nearest the unconstrained
    # projection is the band edge on the side the sum overshot: too large means come down to
    # band_high, too small means come up to band_low. Targeting the far edge would still satisfy
    # the budget while moving every weight further from desired than necessary.
    target = band_high if zero > band_high else band_low

    breakpoints = sorted(
        {_fraction(desired[name]) - _fraction(lower[name]) for name in free}
        | {_fraction(desired[name]) - _fraction(upper[name]) for name in free}
    )
    # The clipped sum is non-increasing in lam, so scanning breakpoints upward walks the sum down
    # from its maximum. On each segment the free set is fixed and the sum is affine, which is what
    # makes an exact solve possible.
    edges = [breakpoints[0] - 1, *breakpoints, breakpoints[-1] + 1]
    for left, right in pairwise(edges):
        high_value = _clipped_sum(left, free, desired, lower, upper)
        low_value = _clipped_sum(right, free, desired, lower, upper)
        if not low_value <= target <= high_value:
            continue
        midpoint = (left + right) / 2
        interior = tuple(
            name
            for name in free
            if _fraction(lower[name]) < _fraction(desired[name]) - midpoint < _fraction(upper[name])
        )
        if not interior:
            # A flat segment: the sum cannot move here, so it already equals the target or the
            # target belongs to a neighbouring segment.
            if high_value == target:
                return left
            continue
        offset = _clipped_sum(midpoint, free, desired, lower, upper) + midpoint * len(interior)
        return (offset - target) / len(interior)

    raise OptimizeRefusal(
        f"no multiplier places the clipped free sum inside [{band_low}, {band_high}]"
    )
