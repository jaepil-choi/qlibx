"""What a strategy returns: `Hold` or `Rebalance`.

`Hold` is no decision: the book and any intent already pending stay as they are. `Rebalance` names
one complete desired portfolio -- weights, cash and the budget they satisfy -- which is the decision
the framework exists to take; to empty the book is an empty `Rebalance`, not a `Hold`. Both are
strict, frozen values the author constructs, so a wrong shape is refused at the boundary the author
can see, with the offending names quoted, rather than several layers into the engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, field_validator, model_validator

from vqapr.component._validation import (
    _VALUE_CONFIG,
    _copy_weights,
    _identifier,
)
from vqapr.data.panel import CrossSection
from vqapr.domain.intent import Budget, PortfolioDirection
from vqapr.portfolio.optimize import QUANTUM
from vqapr.portfolio.weights import rescale

__all__ = [
    "_MAX_OFFENDERS",
    "Hold",
    "Rebalance",
    "_as_decimal",
    "_offenders",
    "_relative_side",
]


class Hold(BaseModel):
    """A Strategy decision that intentionally emits no order.

    **This is the engine's decline type as well as the author's.** It absorbed
    `models.strategy_model.NoDecision` in record `125`: the two were the same frozen one-field
    dataclass with two names, and the adapter's whole contribution was `NoDecision(hold.reason)`.

    `reason` is prose, not an identifier. It was validated with `_identifier` here, which rejects
    whitespace -- so `Hold(reason="no name scored above zero")` was refused while the engine's
    `NoDecision` accepted the identical string. Merging two types means merging two validations,
    and the looser one is the correct one: a reason a human reads should be allowed spaces.
    """

    model_config = _VALUE_CONFIG

    reason: str

    @field_validator("reason")
    @classmethod
    def _prose(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must be a non-empty string")
        return value


def _as_decimal(value: Decimal | int | float | str, *, name: str) -> Decimal:
    """One conviction as an exact Decimal.

    `Decimal(str(v))` for a float rather than `Decimal(v)`: a float64 `0.1` is not one tenth, and
    binding the binary expansion here would put the error into every weight downstream.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be a Decimal, int, float, or string")
    try:
        return Decimal(str(value))
    except ArithmeticError as invalid:
        raise ValueError(f"{name} must be a finite number; got {value!r}") from invalid


def _relative_side(
    declared: Mapping[str, Decimal | int | float | str] | None, *, name: str
) -> dict[str, Decimal]:
    """One side of the book as non-negative relative convictions.

    A short is declared by WHICH MAPPING it appears in, never by its sign, so `short={"A": 2}`
    means twice as short rather than half as long. Accepting a negative here would give one
    intention two spellings that disagree.

    A zero is accepted and means "hold none of this name", the flat position `Rebalance.signed`
    keeps (report 2026-09-11, record `260`): a tilt that floors at zero produced it, and refusing
    it made every such author filter their own mapping before handing it over.
    """
    if declared is None:
        return {}
    if not isinstance(declared, Mapping):
        raise TypeError(f"{name} must be a mapping of instrument to relative weight")
    side: dict[str, Decimal] = {}
    for instrument, raw in declared.items():
        conviction = _as_decimal(raw, name=f"{name}[{instrument!r}]")
        if not conviction.is_finite():
            raise ValueError(f"{name}[{instrument!r}] must be finite")
        if conviction < 0:
            raise ValueError(
                f"{name}[{instrument!r}] must not be negative: a side is chosen by which mapping "
                f"the name appears in, not by the sign of its weight (a zero holds none of it)"
            )
        side[_identifier(instrument, name="instrument")] = conviction
    return side


_MAX_OFFENDERS = 5
"""How many offending weights a `Rebalance` refusal quotes; the rest are counted."""


def _offenders(weights: Mapping[str, Decimal]) -> str:
    """`name=value` for the first few offending weights, and a count of the rest.

    Bounded the way `Failure.examples` is bounded: a thousand-name book that misses a bound on
    every name should say so in one line, not in a thousand.
    """
    shown = [f"{name}={value}" for name, value in list(weights.items())[:_MAX_OFFENDERS]]
    rest = len(weights) - len(shown)
    return ", ".join(shown) + (f", and {rest} more" if rest > 0 else "")


class Rebalance(BaseModel):
    """A Strategy decision naming one complete desired portfolio.

    Three ways in, and the direct constructor is the last of them:

    - `Rebalance.of(long=, short=, invested=)` -- relative conviction per side, split evenly.
    - `Rebalance.signed(weights, gross=)` -- signed weights, split as the signal produced them.
    - `Rebalance(target_weights=, cash_weight=, budget=)` -- everything stated, nothing derived.

    Weights are validated **to the last digit**: `sum(target_weights) + cash_weight` must equal
    one exactly, and a value off by a single ulp is refused by the same invariant that catches a
    real mistake. That is why the two constructors exist, and why anyone building this directly
    should quantise and settle through `vqapr.portfolio.weights.rescale` on the canonical grid
    `vqapr.portfolio.optimize.QUANTUM` rather than by hand (`docs/issues/archive/075`).

    `target_weights` takes any `Mapping[str, Decimal]` and is held as the read-only
    `CrossSection` it validates into.
    """

    model_config = _VALUE_CONFIG

    target_weights: CrossSection[Decimal]
    cash_weight: Decimal
    budget: Budget

    def __init__(
        self, *, target_weights: Mapping[str, Decimal], cash_weight: Decimal, budget: Budget
    ) -> None:
        # The door's own signature: any mapping in, the validated cross-section held. Written
        # out so a type checker accepts the dict every author and both constructors pass.
        super().__init__(target_weights=target_weights, cash_weight=cash_weight, budget=budget)

    @classmethod
    def of(
        cls,
        *,
        long: Mapping[str, Decimal | int | float | str] | None = None,
        short: Mapping[str, Decimal | int | float | str] | None = None,
        invested: Decimal | int | float | str = 1,
    ) -> Rebalance:
        """Build a portfolio from RELATIVE conviction, letting the package do the arithmetic.

        The author says which names they like and how much they like them relative to each other.
        Everything that follows -- normalising each side, splitting the invested fraction between
        the sides, rounding onto the canonical grid, and making the whole thing add up with cash
        -- is arithmetic with exactly one right answer, and a research author who does it by hand
        is spending attention on bookkeeping instead of on the signal.

        `invested` is GROSS exposure **bounded to `0 < invested <= 1`**, so a dollar-neutral
        long/short book at `invested=1` puts the whole book to work and still nets to zero; its
        cash is 1. A short-only book's cash exceeds 1, because selling short raises cash. Cash is
        always the NET residual, never `1 - invested`.

        **The bound and the even split compose, and together they set the ceiling.** Two sides
        each take `invested / 2`, so `invested=1` on a signed book is 0.5 long and 0.5 short --
        not 1.0 and -1.0. The most this constructor can express is therefore half of a textbook
        $1-long/$1-short book, and a published SMB or HML series quoted at that scale is twice
        what comes out of here. Read a factor return built this way as half-scale, or double it
        before comparing.

        Neither the bound nor the split is an accounting invariant. A `Rebalance` with weights
        `+1/-1` and cash 1 satisfies every downstream invariant -- the signed budget admits
        positions in `[-1, 1]` and cash in `[-1, 2]` -- so the ceiling is this constructor's, not
        the account's. Build the `Rebalance` directly to go past it.

        Two sides are currently split evenly, so a 130/30 cannot be expressed through this
        constructor either. Stated rather than implied, because the even split is a choice and not
        a law. **`Rebalance.signed` is the constructor for a book the signal splits**: it takes
        signed weights, normalises them to a gross of your choosing, and leaves the long/short
        ratio exactly as the signal produced it.

        Doing it by hand is also where the errors live: the sum must land on one EXACTLY, and a
        weight that misses by a single ulp is refused by the same invariant that catches a real
        mistake. Relative weights cannot make that error, because the author never states a total.

        `invested` is the fraction of NAV to put to work; the remainder stays in cash. Passing a
        short book implies a signed budget, and a long-only book keeps `LONG_ONLY`, so the budget
        follows from what was actually asked for rather than being declared a second time.

        The two budgets this makes, as values: a long-only book gets targets in `[0, 1]` and cash
        in `[0, 1]`; a signed book gets targets in `[-1, 1]` and cash in `[-1, 2]`, the upper bound
        being 2 because selling short raises cash.

        Quantising and settling belong to `vqapr.portfolio.weights.rescale`, which this calls
        (`docs/issues/archive/075`). Each side lands EXACTLY on its target, on the canonical grid
        `QUANTUM`, with the rounding residual on that side's largest position.

        **A zero holds none of the name.** `long={"A": 0}` keeps A in the book at weight zero --
        the flat position `signed` keeps -- so the next fill sells whatever is held of it, and a
        tilt that floors at zero hands its mapping over unfiltered. A side made only of zeros is
        no side: it takes none of `invested` and does not make the book signed (record `260`).
        """
        longs = _relative_side(long, name="long")
        shorts = _relative_side(short, name="short")
        if not longs and not shorts:
            raise ValueError("a Rebalance needs at least one long or short name")
        live_longs = {name: value for name, value in longs.items() if value}
        live_shorts = {name: value for name, value in shorts.items() if value}
        if not live_longs and not live_shorts:
            raise ValueError(
                "a Rebalance needs at least one non-zero weight; every weight given was zero, "
                "and a book of nothing has no side to size"
            )

        # A name on both sides is a contradiction, not a netting instruction. Silently letting the
        # short overwrite the long drops a leg the author wrote, and the resulting book is not
        # what either mapping asked for.
        both = sorted(set(longs) & set(shorts))
        if both:
            raise ValueError(
                f"cannot be long and short the same name: {', '.join(both)}. "
                "Net them yourself and declare the side you actually want"
            )

        share = _as_decimal(invested, name="invested")
        if not 0 < share <= 1:
            raise ValueError(
                f"invested must be greater than zero and no greater than one; got {share}. "
                "It is GROSS exposure and both sides split it evenly, so the most a signed book "
                "can reach through this constructor is 0.5 long and 0.5 short. A textbook "
                "$1-long/$1-short book is twice that and cannot be expressed here -- build the "
                "Rebalance directly if you need it."
            )

        # Both sides present means the book is signed and each side takes half the invested
        # fraction. One side alone takes all of it. Quantised here because it becomes a side
        # TARGET below, and `rescale` refuses a target that is not itself on the grid -- weights
        # on a grid cannot sum to a total that is off it.
        sides = (bool(live_longs), bool(live_shorts))
        per_side = (share / 2 if all(sides) else share).quantize(QUANTUM)
        if per_side == 0:
            raise ValueError(
                f"invested {share} is smaller than the canonical grid {QUANTUM} once split "
                f"between {'two sides' if all(sides) else 'the book'}, so every weight would "
                "round to zero. Ask for at least one grid step per side"
            )
        weights: dict[str, Decimal] = {}
        for names, live, sign in (
            (longs, live_longs, Decimal(1)),
            (shorts, live_shorts, Decimal(-1)),
        ):
            total = sum(live.values(), Decimal(0))
            for instrument, conviction in names.items():
                weights[instrument] = (
                    sign * per_side * conviction / total if conviction else Decimal(0)
                )

        # `rescale` owns quantising and settling, and this constructor stopped owning a second copy
        # of it (`docs/issues/archive/075`). It quantises onto the grid FIRST and settles each
        # side's rounding residual afterwards, on that side's largest position by absolute size --
        # where the crumb is proportionally smallest, and where it cannot move cash across a bound.
        # Settling in CASH is the obvious-looking alternative and is wrong for a measurable reason:
        # a dollar-neutral signed book nets to zero, so its cash is 1, and three shorts at -0.5/3
        # leave -1e-12, which pushes cash to 1.000000000001 -- one crumb ABOVE the fully-uninvested
        # bound. The book is arithmetically fine and the declaration is refused. PER SIDE, not per
        # book, which is what changed here. Settling one book-wide residual on the single largest
        # position let a crumb from the SHORT side land on a LONG name, so a book asking for
        # `invested=1` could come out with gross 1.000000000002 -- and `invested` is documented as
        # gross exposure. Each side now lands exactly on its own target, so gross is exact and the
        # two sides of a neutral book cancel on the same grid steps.
        quantised = dict(
            rescale(
                dict(sorted(weights.items())),
                long=per_side if live_longs else Decimal(0),
                short=-per_side if live_shorts else Decimal(0),
                grid=QUANTUM,
            )
        )

        # Cash is what the book does NOT hold net, and for a signed book that is not
        # `1 - invested`. `invested` is GROSS exposure: a dollar-neutral long/short book puts the
        # whole invested fraction to work and still nets to zero, so its cash is 1. Computing cash
        # from the gross fraction produced a residual of ~1 and a refusal on a book that is
        # arithmetically perfect.
        #
        # Exact by construction now: every side landed on its target, so the sum is on the grid
        # and no second settle is needed here.
        cash = Decimal(1) - sum(quantised.values(), Decimal(0))
        if live_shorts:
            direction = PortfolioDirection.SIGNED
            bounds = (Decimal(-1), Decimal(1))
            # Cash can exceed 1 on a signed book, and pinning the upper bound at 1 made every
            # SHORT-ONLY book refuse -- 100% of them, with a message naming cash when the real
            # problem was a bound that cannot represent short-sale proceeds. Selling short raises
            # cash: a book that is only short holds MORE than its NAV in cash by exactly the
            # amount it shorted. The bound is widened to admit that rather than the arithmetic
            # being bent to fit a bound that was wrong.
            cash_bounds = (Decimal(-1), Decimal(2))
        else:
            direction = PortfolioDirection.LONG_ONLY
            bounds = (Decimal(0), Decimal(1))
            cash_bounds = (Decimal(0), Decimal(1))
        return cls(
            target_weights=quantised,
            cash_weight=cash,
            budget=Budget(
                direction=direction,
                cash_lower=cash_bounds[0],
                cash_upper=cash_bounds[1],
                target_lower=bounds[0],
                target_upper=bounds[1],
            ),
        )

    @classmethod
    def signed(
        cls,
        weights: Mapping[str, Decimal | int | float | str],
        *,
        gross: Decimal | int | float | str = 1,
    ) -> Rebalance:
        """Build a signed book from signed weights, split exactly as the signal produced them.

        This is the market-neutral residual book `docs/issues/archive/075` was filed on, and the
        thing `of` structurally cannot say. `of` takes two mappings and splits `invested` EVENLY
        between them, so it tops out at half a textbook $1-long/$1-short book
        (`docs/issues/archive/018`) and can never express a 130/30 or a book whose signal happened
        to find more shorts than longs. Here the ratio is the signal's: pass what the signal
        produced, say how large the book should be, and the long/short split falls out of the
        weights themselves.

        **The sign carries the side.** A negative weight is a short, which is the opposite
        convention to `of` -- there, the side is chosen by WHICH MAPPING a name appears in and a
        negative number is refused. The two constructors take different inputs, so they can afford
        different conventions; what they must not do is accept the same input and mean different
        things by it.

        `gross` is the sum of ABSOLUTE weights, so `gross=1` on a dollar-neutral book is 0.5 long
        and 0.5 short, and `gross=2` is the textbook $1/$1 book `of` cannot reach. It is not
        bounded at 1: leverage is a real declaration, and the budget below admits positions in
        `[-1, 1]` with cash in `[-1, 2]`, which is what actually constrains the book.

        Cash is the NET residual, `1 - sum(weights)` -- not `1 - gross`. A dollar-neutral book is
        fully invested and nets to zero, so its cash is 1; a book that is only short holds more
        than its NAV in cash by exactly what it shorted.

        A name whose weight is zero is kept as a flat position rather than dropped: a signal that
        scores a name at zero has said something about it, and silently removing the name would
        make the returned book disagree with the mapping the author passed.

        Quantising and settling are `vqapr.portfolio.weights.rescale`'s, on the canonical grid,
        each side landing exactly on its own target.
        """
        if not isinstance(weights, Mapping) or not weights:
            raise TypeError("weights must be a non-empty mapping of instrument to signed weight")
        declared: dict[str, Decimal] = {}
        for instrument, raw in weights.items():
            value = _as_decimal(raw, name=f"weights[{instrument!r}]")
            if not value.is_finite():
                raise ValueError(f"weights[{instrument!r}] must be finite")
            declared[_identifier(instrument, name="instrument")] = value

        size = _as_decimal(gross, name="gross")
        if size <= 0:
            raise ValueError(
                f"gross must be greater than zero; got {size}. It is the sum of ABSOLUTE weights, "
                "so a dollar-neutral book at gross=1 is 0.5 long and 0.5 short"
            )

        total = sum((abs(value) for value in declared.values()), Decimal(0))
        if total == 0:
            raise ValueError(
                "a Rebalance needs at least one non-zero weight; every weight given was zero, "
                "and a book of nothing has no side to size"
            )

        # The two side targets, in the ratio the SIGNAL produced -- this is the whole point of
        # this constructor. Quantised because `rescale` refuses a target that is not itself on
        # the grid, which can leave `long + (-short)` one step away from `gross`; that is the
        # grid's own resolution and not a miscalculation.
        longs = sum((value for value in declared.values() if value > 0), Decimal(0))
        shorts = sum((value for value in declared.values() if value < 0), Decimal(0))
        long_target = (size * longs / total).quantize(QUANTUM)
        short_target = (size * shorts / total).quantize(QUANTUM)
        for name, side, target in (("long", longs, long_target), ("short", shorts, short_target)):
            if side != 0 and target == 0:
                raise ValueError(
                    f"the {name} side is {side} of a gross {size}, which is smaller than the "
                    f"canonical grid {QUANTUM} and would round the whole side to zero. Raise "
                    "gross, or drop the side from the weights"
                )

        book = dict(rescale(declared, long=long_target, short=short_target, grid=QUANTUM))
        return cls(
            target_weights=book,
            cash_weight=Decimal(1) - sum(book.values(), Decimal(0)),
            # SIGNED unconditionally, even for an all-positive mapping: the author reached for the
            # signed constructor and the next signal may find a short. A budget that flipped to
            # LONG_ONLY on the days a signal happened to find none would refuse the book on the
            # first day it did.
            budget=Budget(
                direction=PortfolioDirection.SIGNED,
                cash_lower=Decimal(-1),
                cash_upper=Decimal(2),
                target_lower=Decimal(-1),
                target_upper=Decimal(1),
            ),
        )

    @field_validator("target_weights", mode="before")
    @classmethod
    def _weights(cls, value: object) -> CrossSection[Decimal]:
        return _copy_weights(value, name="target_weights")

    @model_validator(mode="after")
    def _adds_up_inside_the_budget(self) -> Self:
        # The fields are already what they claim: a read-only cross-section of finite Decimals,
        # a finite cash weight, a Budget. What is checked here is the relation between them.
        weights, cash, budget = self.target_weights, self.cash_weight, self.budget
        # Every refusal here names the value it saw and the bound it crossed. These five said
        # only the rule -- `cash_weight is outside the declared budget` -- and an author whose
        # quantised shorts summed to -1.000000000001 had to reason the cash of 2.000000000001 and
        # the bound of 2 out by hand, in a run of eight strategies (`docs/issues/archive/071`).
        if not budget.validates_cash(cash):
            raise ValueError(
                f"cash_weight {cash} is outside the declared budget "
                f"[{budget.cash_lower}, {budget.cash_upper}]"
            )
        if weights:
            outside = {
                name: value
                for name, value in weights.items()
                if not budget.validates_target(value)
            }
            if outside:
                raise ValueError(
                    "target_weights are outside the declared budget bounds "
                    f"[{budget.target_lower}, {budget.target_upper}]: {_offenders(outside)}"
                )
            if budget.direction is PortfolioDirection.LONG_ONLY:
                negative = {name: value for name, value in weights.items() if value < 0}
                if negative:
                    raise ValueError(
                        f"long_only budgets forbid negative target_weights: {_offenders(negative)}"
                    )
            total = sum(weights.values(), Decimal(0))
            if total + cash != 1:
                raise ValueError(
                    "target_weights plus cash_weight must equal one; got "
                    f"sum(target_weights) {total} + cash_weight {cash} = {total + cash}"
                )
        elif cash != 1:
            raise ValueError(
                f"an empty complete position set requires cash_weight equal to one; got {cash}"
            )
        return self
