"""Closed valuation service: every held position needs an explicit selected mark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.valuation.marks import Mark, MarkBatch


class ValuationError(ValueError):
    """A valuation failure retaining the already committed account version."""

    def __init__(self, message: str, *, account_version: int) -> None:
        super().__init__(message)
        self.account_version = account_version


@dataclass(frozen=True, slots=True)
class SelectedMark:
    """One caller-selected mark input; no prior-price fallback exists."""

    instrument_id: str
    price: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        if not isinstance(self.price, Decimal):
            raise TypeError("price must be a Decimal")
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("price must be finite and positive")


class ValuationService:
    """Materialize a complete mark batch from explicit marks and an account snapshot."""

    def mark(
        self,
        account: AccountSnapshot,
        selected_marks: Mapping[str, Decimal] | tuple[SelectedMark, ...],
    ) -> MarkBatch:
        if not isinstance(account, AccountSnapshot):
            raise TypeError("account must be an AccountSnapshot")
        prices = self._prices(selected_marks, account.version)
        positions = account.positions
        if not isinstance(positions, Mapping):
            raise TypeError("AccountSnapshot.positions must be a mapping")
        held = tuple(
            sorted(
                (instrument, quantity)
                for instrument, quantity in positions.items()
                if quantity != 0
            )
        )
        marks: list[Mark] = []
        for instrument, quantity in held:
            if not isinstance(instrument, str) or not instrument:
                raise ValuationError(
                    "account contains an invalid instrument identity",
                    account_version=account.version,
                )
            if not isinstance(quantity, Decimal) or not quantity.is_finite():
                raise ValuationError(
                    f"account contains an invalid quantity for {instrument!r}",
                    account_version=account.version,
                )
            price = prices.get(instrument)
            if price is None:
                raise ValuationError(
                    f"missing selected mark for {instrument!r}", account_version=account.version
                )
            marks.append(Mark(instrument, quantity, price, quantity * price))
        return MarkBatch(tuple(marks), sum((mark.value for mark in marks), Decimal("0")))

    @staticmethod
    def _prices(
        selected_marks: Mapping[str, Decimal] | tuple[SelectedMark, ...], account_version: int
    ) -> dict[str, Decimal]:
        if isinstance(selected_marks, Mapping):
            items = tuple(selected_marks.items())
        elif isinstance(selected_marks, tuple) and all(
            isinstance(mark, SelectedMark) for mark in selected_marks
        ):
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
