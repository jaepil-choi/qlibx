"""Pure order sizing from execution-session prices and committed account state.

Sizing NAV intentionally uses the current execution-session prices, not the mark-based NAV carried
by the account snapshot. This keeps quantity conversion aligned with the declared sizing price role.
"""

import math
from dataclasses import dataclass
from datetime import date

from pydantic import Field

from qlibx.context import StateAccessRecord
from qlibx.domain import Side
from qlibx.execution.exchange import Order
from qlibx.models import QlibxModel


class SizingTarget(QlibxModel):
    instrument_id: str = Field(min_length=1)
    weight: float = Field(ge=0)


class SizingPrice(QlibxModel):
    instrument_id: str = Field(min_length=1)
    price: float


class SessionSizingRequest(QlibxModel):
    session_date: date
    sizing_price_role: str = Field(min_length=1)
    targets: tuple[SizingTarget, ...]


class SessionSizingInput(QlibxModel):
    account_state: StateAccessRecord
    prices: tuple[SizingPrice, ...]


@dataclass(frozen=True, slots=True)
class SessionSizing:
    sizing_nav: float
    required_instruments: tuple[str, ...]
    orders: tuple[Order, ...]


class SizingError(ValueError):
    def __init__(self, code: str, context: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.context = context


def size_session_orders(
    request: SessionSizingRequest,
    source: SessionSizingInput,
) -> SessionSizing:
    """Convert target weights into deterministic sell-first share orders."""

    prices = {
        item.instrument_id: item.price
        for item in source.prices
        if math.isfinite(item.price) and item.price > 0
    }
    target_weights = {item.instrument_id: item.weight for item in request.targets}
    holdings = {
        item.instrument_id: item.quantity for item in source.account_state.holdings
    }
    required_instruments = tuple(sorted(set(target_weights) | set(holdings)))
    missing = tuple(
        instrument for instrument in required_instruments if instrument not in prices
    )
    if missing:
        raise SizingError(
            "EXECUTION_SESSION_PRICE_MISSING",
            {
                "session": str(request.session_date),
                "instruments": list(missing[:20]),
            },
        )

    sizing_nav = source.account_state.cash + sum(
        holdings[instrument] * prices[instrument] for instrument in holdings
    )
    if not math.isfinite(sizing_nav) or sizing_nav <= 0:
        raise SizingError(
            "EXECUTION_SIZING_NAV_INVALID",
            {"sizing_nav": sizing_nav},
        )

    orders: list[Order] = []
    for instrument in required_instruments:
        target_quantity = target_weights.get(instrument, 0) * sizing_nav / prices[instrument]
        actual_quantity = holdings.get(instrument, 0)
        delta = target_quantity - actual_quantity
        if delta > 1e-12:
            orders.append(Order(instrument, Side.BUY, delta))
        elif delta < -1e-12:
            orders.append(Order(instrument, Side.SELL, -delta))
    orders.sort(key=lambda order: (0 if order.side is Side.SELL else 1, order.instrument_id))
    return SessionSizing(
        sizing_nav=sizing_nav,
        required_instruments=required_instruments,
        orders=tuple(orders),
    )