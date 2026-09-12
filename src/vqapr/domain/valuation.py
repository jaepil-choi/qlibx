"""Valuation: which price each held position is marked at, chosen explicitly.

`select_prices` chooses from what the venue published at an instant: a fresh row marks a name, a
name the venue published nothing for carries its previous mark forward with the instant that mark
was observed, and a name with neither is left unpriced. `SelectedMark` is one such choice;
`prices_of` checks the choices and hands `Account.mark` the price map it multiplies the book by.
The multiplication is the account's own (`AccountSnapshot.value`, record `276`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from vqapr.domain.account import AccountMark
from vqapr.domain.instants import require_tz_aware

__all__ = [
    "SelectedMark",
    "ValuationError",
    "prices_of",
    "select_prices",
]


class ValuationError(ValueError):
    """A valuation failure retaining the already committed account version."""

    def __init__(self, message: str, *, account_version: int) -> None:
        super().__init__(message)
        self.account_version = account_version


@dataclass(frozen=True, slots=True)
class SelectedMark:
    """One selected mark and the instant the price it carries was observed.

    A held instrument is marked from the newest observation at or before the valuation cutoff.
    When the instrument traded that session those two instants coincide; when it is halted or has
    delisted the observation is older, and the position is carried at that earlier price rather
    than being written down to nothing.

    ``observed_at`` is recorded because valuation cannot tell those cases apart. A three-month
    halt and a delisting look identical at the cutoff and are distinguished only by whether the
    instrument trades again, which is a fact from the future. So valuation records **which price
    it used and when that price was observed**, and reporting decides afterwards what the gap
    meant.
    """

    instrument_id: str
    price: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if not isinstance(self.price, Decimal):
            raise TypeError("price must be a Decimal")
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("price must be finite and positive")
        require_tz_aware(self.observed_at, name="observed_at")

    def staleness(self, cutoff: datetime) -> timedelta:
        """How far before `cutoff` this price was observed.

        Zero for an instrument that traded at the cutoff. A positive value is a fact, not a
        verdict: it says the price is older, not why.
        """
        return require_tz_aware(cutoff, name="cutoff") - self.observed_at


def select_prices(
    snapshot: object,
    target_at: datetime,
    *,
    previous: AccountMark | None = None,
    held: Mapping[str, Decimal] | None = None,
) -> tuple[SelectedMark, ...]:
    """Value the book from the prices the venue published as executable at this instant.

    A row with a price marks the name, **including when `is_tradable` is false**: the venue
    published a price, and refusing to trade is a different fact from refusing to quote.

    A name the venue published nothing for **carries its previous mark forward, keeping the
    instant that mark was originally observed at**. A halt is not a reason to write a holding
    down, and it is not a reason to drop it out of NAV either; it is a reason for its price to
    stop moving. `SelectedMark.staleness(cutoff)` is what makes the gap visible afterwards.

    A name with no row and no previous mark produces nothing. That is a position the venue has
    never priced, so there is no honest number to put in the denominator.
    """
    marks: dict[str, SelectedMark] = {}
    for row in getattr(snapshot, "rows", ()):
        price = row.price
        if price is None or price <= 0:
            continue
        marks[row.instrument] = SelectedMark(row.instrument, price, target_at)
    if previous is not None and held is not None:
        for carried in previous.marks.marks:
            if carried.instrument_id in marks or carried.instrument_id not in held:
                continue
            observed_at = _observed_at(previous, carried.instrument_id)
            if observed_at is None:
                continue
            marks[carried.instrument_id] = SelectedMark(
                carried.instrument_id, carried.price, observed_at
            )
    return tuple(marks[instrument] for instrument in sorted(marks))


def _observed_at(mark: AccountMark, instrument: str) -> datetime | None:
    """When the carried price was actually observed, not when it was carried.

    A mark taken before this design carries no instant; it cannot claim one retroactively.
    """
    selected = mark.observed_at_by_instrument
    if selected is not None:
        return selected.get(instrument, mark.marked_at)
    return mark.marked_at


def prices_of(
    selected_marks: Mapping[str, Decimal] | tuple[SelectedMark, ...], *, account_version: int
) -> dict[str, Decimal]:
    """The price map `Account.mark` multiplies the book by, from explicit choices.

    Refuses what no price map may hold: an empty identity, one name chosen twice, a price that
    is not finite and positive. The failure keeps the account version it would have valued.
    """
    if isinstance(selected_marks, Mapping):
        items = tuple(selected_marks.items())
    elif isinstance(selected_marks, tuple) and all(
        isinstance(mark, SelectedMark) for mark in selected_marks
    ):
        # The observation instant rides on the input and stays in the evidence; only the
        # price is needed to value the position.
        items = tuple((mark.instrument_id, mark.price) for mark in selected_marks)
    else:
        raise TypeError("selected_marks must be a mapping or a tuple of SelectedMark")
    prices: dict[str, Decimal] = {}
    for instrument, price in items:
        if not isinstance(instrument, str) or not instrument:
            raise ValuationError(
                "selected marks contain an invalid instrument identity",
                account_version=account_version,
            )
        if instrument in prices:
            raise ValuationError(
                f"selected marks contain duplicate identity {instrument!r}",
                account_version=account_version,
            )
        if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
            raise ValuationError(
                f"selected mark for {instrument!r} must be finite and positive",
                account_version=account_version,
            )
        prices[instrument] = price
    return prices
