"""Closed academic execution policy at the Exchange extension boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from vqapr.account.snapshot import AccountSnapshot
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.orders.batches import OrderBatch, OrderRequest


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class ListingRule:
    """A venue-owned rule for one listed instrument."""

    instrument_id: str
    quantity_step: Decimal
    minimum_quantity: Decimal
    fractional_allowed: bool
    permitted_sides: frozenset[Side]

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, str) or not self.instrument_id:
            raise ValueError("instrument_id must be a non-empty string")
        for name, value in (
            ("quantity_step", self.quantity_step),
            ("minimum_quantity", self.minimum_quantity),
        ):
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.fractional_allowed, bool):
            raise TypeError("fractional_allowed must be a bool")
        if not isinstance(self.permitted_sides, frozenset) or not self.permitted_sides:
            raise ValueError("permitted_sides must be a non-empty frozenset")
        if any(not isinstance(side, Side) for side in self.permitted_sides):
            raise TypeError("permitted_sides must contain Side values")


class Exchange(Protocol):
    """The deliberately small execution extension boundary."""

    exchange_id: str

    def execute(
        self, orders: OrderBatch, account: AccountSnapshot, snapshot: ExactExecutionSnapshot
    ) -> FillBatch: ...


def _side(quantity: Decimal) -> Side | None:
    if quantity > 0:
        return Side.BUY
    if quantity < 0:
        return Side.SELL
    return None


def _is_step_aligned(quantity: Decimal, step: Decimal) -> bool:
    return (abs(quantity) / step).to_integral_value() == abs(quantity) / step


@dataclass(frozen=True, slots=True)
class AcademicExchange:
    """Zero-friction, full-fill execution for declared academic listings."""

    listings: Mapping[str, ListingRule]
    exchange_id: str = "academic"

    def __post_init__(self) -> None:
        if not isinstance(self.exchange_id, str) or not self.exchange_id:
            raise ValueError("exchange_id must be a non-empty string")
        if not isinstance(self.listings, Mapping):
            raise TypeError("listings must be a mapping")
        copied = dict(self.listings)
        for instrument_id, rule in copied.items():
            if not isinstance(rule, ListingRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its ListingRule instrument_id")
        object.__setattr__(self, "listings", copied)

    def execute(
        self, orders: OrderBatch, account: AccountSnapshot, snapshot: ExactExecutionSnapshot
    ) -> FillBatch:
        """Validate global prerequisites, then return every order in stable identity order."""
        if not isinstance(orders, OrderBatch):
            raise TypeError("orders must be an OrderBatch")
        if not isinstance(account, AccountSnapshot):
            raise TypeError("account must be an AccountSnapshot")
        if not isinstance(snapshot, ExactExecutionSnapshot):
            raise TypeError("snapshot must be an ExactExecutionSnapshot")
        if orders.account_version != account.version:
            raise ValueError("OrderBatch account_version does not match AccountSnapshot version")

        requests = tuple(sorted(orders.requests, key=lambda request: request.instrument_id))
        if len({request.instrument_id for request in requests}) != len(requests):
            raise ValueError("an OrderBatch may contain each instrument only once")
        self._validate_rules(requests)
        rows = self._validate_snapshot(snapshot, requests)

        fills: list[Fill] = []
        for request in requests:
            if request.delta_quantity == 0:
                fills.append(
                    Fill(
                        request.instrument_id,
                        Decimal("0"),
                        Decimal("0"),
                        None,
                        ZeroDealtReason.NO_TRADE,
                    )
                )
                continue
            row = rows.get(request.instrument_id)
            if row is None:
                fills.append(
                    Fill(
                        request.instrument_id,
                        request.delta_quantity,
                        Decimal("0"),
                        None,
                        ZeroDealtReason.ABSENT,
                    )
                )
            elif not row.is_tradable:
                fills.append(
                    Fill(
                        request.instrument_id,
                        request.delta_quantity,
                        Decimal("0"),
                        None,
                        ZeroDealtReason.NONTRADABLE,
                    )
                )
            else:
                fills.append(
                    Fill(
                        request.instrument_id,
                        request.delta_quantity,
                        request.delta_quantity,
                        row.price,
                    )
                )
        return FillBatch(tuple(fills), account.version)

    def _validate_rules(self, requests: tuple[OrderRequest, ...]) -> None:
        for request in requests:
            if (
                not isinstance(request.delta_quantity, Decimal)
                or not request.delta_quantity.is_finite()
            ):
                raise ValueError(f"invalid requested quantity for {request.instrument_id!r}")
            if (
                not isinstance(request.execution_price, Decimal)
                or not request.execution_price.is_finite()
                or request.execution_price <= 0
            ):
                raise ValueError(f"invalid selected price for {request.instrument_id!r}")
            rule = self.listings.get(request.instrument_id)
            if rule is None:
                raise ValueError(f"no academic listing for {request.instrument_id!r}")
            side = _side(request.delta_quantity)
            if side is None:
                continue
            if side not in rule.permitted_sides:
                raise ValueError(f"{side.value} is not permitted for {request.instrument_id!r}")
            quantity = abs(request.delta_quantity)
            if quantity < rule.minimum_quantity or not _is_step_aligned(
                quantity, rule.quantity_step
            ):
                raise ValueError(f"quantity violates listing rule for {request.instrument_id!r}")
            if not rule.fractional_allowed and quantity != quantity.to_integral_value():
                raise ValueError(
                    f"fractional quantity is not permitted for {request.instrument_id!r}"
                )

    @staticmethod
    def _validate_snapshot(
        snapshot: ExactExecutionSnapshot, requests: tuple[OrderRequest, ...]
    ) -> dict[str, ExactExecutionRow]:
        requested = {request.instrument_id for request in requests if request.delta_quantity != 0}
        if set(snapshot.duplicate_instruments) & requested:
            raise ValueError("execution snapshot has duplicate requested instruments")
        rows: dict[str, ExactExecutionRow] = {}
        for row in snapshot.rows:
            if row.instrument not in requested:
                continue
            if row.instrument in rows:
                raise ValueError("execution snapshot has duplicate requested instruments")
            if not isinstance(row.is_tradable, bool):
                raise ValueError(f"invalid tradability for {row.instrument!r}")
            if row.is_tradable and (
                not isinstance(row.price, Decimal) or not row.price.is_finite() or row.price <= 0
            ):
                raise ValueError(f"invalid tradable price for {row.instrument!r}")
            rows[row.instrument] = row
        return rows
