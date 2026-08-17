"""KRX execution profile.

This profile implements a declared, deliberately partial set of KRX rules. It claims exactly what
it implements and nothing else (PRD 6.3):

Implemented
    whole-share quantity unit, brokerage commission on both sides, sale tax on sells only, halted
    instruments producing typed zero-dealt results, refusal of any order that would open or deepen
    a short position, and full execution of the remainder at the exact selected price.

Not implemented, and therefore not claimed
    price ticks, daily price limits, auction microstructure, queue position, partial fills from
    liquidity or participation limits, borrow and locate for short sales, margin, and any intraday
    behaviour. Costs other than the declared commission and tax are absent, not zero by measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.enums import Side, side_of
from vqapr.exchange.costs import CostRule
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.exchange.listings import ExchangeRulesView, ListingRule
from vqapr.orders.batches import OrderBatch, OrderRequest

COMMISSION_RATE = Decimal("0.0003")
"""Brokerage commission charged on both sides."""

SALE_TAX_RATE = Decimal("0.002")
"""Securities transaction tax charged on sells only."""

SHARE_UNIT = Decimal("1")
"""KRX equities trade in whole shares."""


def krx_cost_rules(
    commission_rate: Decimal = COMMISSION_RATE,
    sale_tax_rate: Decimal = SALE_TAX_RATE,
) -> tuple[CostRule, ...]:
    """The two declared cost bands, one per side."""
    return (
        CostRule("krx-buy", Side.BUY, commission_rate, Decimal("0")),
        CostRule("krx-sell", Side.SELL, commission_rate, sale_tax_rate),
    )


def krx_listing(instrument_id: str) -> ListingRule:
    """A whole-share KRX listing that permits both directions of a long position."""
    return ListingRule(
        instrument_id=instrument_id,
        quantity_step=SHARE_UNIT,
        minimum_quantity=SHARE_UNIT,
        fractional_allowed=False,
        permitted_sides=frozenset({Side.BUY, Side.SELL}),
    )


class KrxExchange:
    """Whole-share KRX execution with declared commission and sale tax, long positions only."""

    exchange_id: str

    def __init__(
        self,
        listings: Mapping[str, ListingRule] | Sequence[str],
        exchange_id: str = "krx",
        costs: Sequence[CostRule] | None = None,
    ) -> None:
        resolved: Mapping[str, ListingRule]
        if isinstance(listings, Mapping):
            resolved = dict(listings)
        else:
            resolved = {instrument: krx_listing(instrument) for instrument in listings}
        for instrument_id, rule in resolved.items():
            if not isinstance(rule, ListingRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its ListingRule instrument_id")
            if rule.fractional_allowed:
                raise ValueError(f"KRX listing {instrument_id!r} must not be fractional")
        self.exchange_id = exchange_id
        self._rules = ExchangeRulesView(
            exchange_id, resolved, tuple(krx_cost_rules() if costs is None else costs)
        )

    @property
    def rules(self) -> ExchangeRulesView:
        """The read-only projection order planning consumes."""
        return self._rules

    @property
    def listings(self) -> Mapping[str, ListingRule]:
        return self._rules.listings

    def execute(
        self, orders: OrderBatch, account: AccountSnapshot, snapshot: ExactExecutionSnapshot
    ) -> FillBatch:
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
        rows = self._rows(snapshot, requests)
        self._validate(requests, rows, account)

        fills: list[Fill] = []
        for request in requests:
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
                continue
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
            if not row.is_tradable:
                fills.append(
                    Fill(
                        request.instrument_id,
                        request.delta_quantity,
                        Decimal("0"),
                        None,
                        ZeroDealtReason.NONTRADABLE,
                    )
                )
                continue
            side = side_of(request.delta_quantity)
            assert side is not None
            notional = abs(request.delta_quantity) * row.price
            fills.append(
                Fill(
                    request.instrument_id,
                    request.delta_quantity,
                    request.delta_quantity,
                    row.price,
                    cost=self._rules.charge(side, notional),
                )
            )
        return FillBatch(tuple(fills), account.version)

    def _validate(
        self,
        requests: tuple[OrderRequest, ...],
        rows: Mapping[str, ExactExecutionRow],
        account: AccountSnapshot,
    ) -> None:
        for request in requests:
            if (
                not isinstance(request.delta_quantity, Decimal)
                or not request.delta_quantity.is_finite()
            ):
                raise ValueError(f"invalid requested quantity for {request.instrument_id!r}")
            rule = self._rules.listing(request.instrument_id)
            row = rows.get(request.instrument_id)
            if (
                row is not None
                and row.is_tradable
                and (
                    not isinstance(request.execution_price, Decimal)
                    or not request.execution_price.is_finite()
                    or request.execution_price <= 0
                )
            ):
                raise ValueError(f"invalid selected price for {request.instrument_id!r}")
            side = side_of(request.delta_quantity)
            if side is None:
                continue
            if not rule.permits(side):
                raise ValueError(f"{side.value} is not permitted for {request.instrument_id!r}")
            quantity = abs(request.delta_quantity)
            if quantity != rule.quantize(quantity):
                raise ValueError(
                    f"quantity {quantity} is not a whole share for {request.instrument_id!r}"
                )
            held = account.positions.get(request.instrument_id, Decimal("0"))
            if held + request.delta_quantity < 0:
                raise ValueError(
                    f"KRX profile does not support short selling {request.instrument_id!r}"
                )

    @staticmethod
    def _rows(
        snapshot: ExactExecutionSnapshot, requests: tuple[OrderRequest, ...]
    ) -> dict[str, ExactExecutionRow]:
        requested = {request.instrument_id for request in requests}
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
