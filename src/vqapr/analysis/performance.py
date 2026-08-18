"""NAV, return and drawdown — read from what a run marked, never derived from prices.

Canon draws a hard line here: `analysis/` reads what was stored and does not manufacture a new
portfolio return. Everything the framework reports about performance comes from the marking and
Account spine, so that a number in a report and a number in the ledger cannot disagree.

That line is enforced by the input type rather than by a docstring. These functions take a
`MarkBatch` — the type the valuation layer produces and the Account commits — and refuse anything
else by name. Handing them a price panel is not a convenience they quietly accommodate; it is the
one mistake that would let a second, unreconciled performance number into the system.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from vqapr.valuation.marks import MarkBatch

__all__ = ["drawdown", "nav_series", "returns"]


def _checked(marks: Sequence[MarkBatch], name: str) -> tuple[MarkBatch, ...]:
    if isinstance(marks, (str, bytes)) or not isinstance(marks, Sequence):
        raise TypeError(f"{name} takes a sequence of MarkBatch")
    if not marks:
        raise ValueError(f"{name} needs at least one mark")
    for index, batch in enumerate(marks):
        if not isinstance(batch, MarkBatch):
            # The refusal names what arrived, because the mistake this guards against is handing
            # in a price panel and getting a plausible-looking number the ledger never agreed to.
            raise TypeError(
                f"{name}[{index}] must be a MarkBatch produced by the valuation spine; "
                f"got {type(batch).__name__}"
            )
    return tuple(marks)


def nav_series(marks: Sequence[MarkBatch], *, cash: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Net asset value at each mark: marked position value plus the cash held alongside it.

    Cash arrives as an argument rather than being inferred, because the Account owns it and this
    module reads rather than reconstructs.
    """
    checked = _checked(marks, "nav_series")
    if isinstance(cash, (str, bytes)) or not isinstance(cash, Sequence):
        raise TypeError("cash must be a sequence of Decimal")
    if len(cash) != len(checked):
        raise ValueError(
            f"cash has {len(cash)} entries for {len(checked)} marks; they must correspond"
        )
    for index, amount in enumerate(cash):
        if not isinstance(amount, Decimal):
            raise TypeError(f"cash[{index}] must be a Decimal; got {type(amount).__name__}")
        if not amount.is_finite():
            raise ValueError(f"cash[{index}] must be finite")
    return tuple(batch.total_value + amount for batch, amount in zip(checked, cash, strict=True))


def returns(nav: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Period returns from a NAV series, one fewer than the NAV values.

    A zero or negative starting value is refused rather than skipped: a return is undefined there,
    and skipping it would silently shorten the series a caller is about to compare against dates.
    """
    if isinstance(nav, (str, bytes)) or not isinstance(nav, Sequence):
        raise TypeError("nav must be a sequence of Decimal")
    if len(nav) < 2:
        raise ValueError("returns needs at least two NAV values")
    for index, value in enumerate(nav):
        if not isinstance(value, Decimal):
            raise TypeError(f"nav[{index}] must be a Decimal; got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"nav[{index}] must be finite")
    produced: list[Decimal] = []
    for index in range(1, len(nav)):
        previous = nav[index - 1]
        if previous <= 0:
            raise ValueError(f"nav[{index - 1}] must be positive to define a return")
        produced.append(nav[index] / previous - 1)
    return tuple(produced)


def drawdown(nav: Sequence[Decimal]) -> tuple[Decimal, ...]:
    """Shortfall from the highest value seen so far, at each point, as a non-positive fraction.

    Running peak rather than final peak, because a drawdown is what an investor was living through
    at the time, not what it looks like once the recovery is known.
    """
    if isinstance(nav, (str, bytes)) or not isinstance(nav, Sequence):
        raise TypeError("nav must be a sequence of Decimal")
    if not nav:
        raise ValueError("drawdown needs at least one NAV value")
    for index, value in enumerate(nav):
        if not isinstance(value, Decimal):
            raise TypeError(f"nav[{index}] must be a Decimal; got {type(value).__name__}")
        if not value.is_finite():
            raise ValueError(f"nav[{index}] must be finite")
        if value <= 0:
            raise ValueError(f"nav[{index}] must be positive to define a drawdown")
    produced: list[Decimal] = []
    peak = nav[0]
    for value in nav:
        peak = max(peak, value)
        produced.append(value / peak - 1)
    return tuple(produced)
