"""The ledger: one shape of entry. The fold that turns entries into a snapshot lives beside
the snapshot (`domain/account_state.py`), so the entry imports nothing that folds it.

Design §5 (`docs/design/two-clocks-and-the-wiring-table.md`): **the account is an append-only
ledger plus an incremental fold.** An entry says what changed -- cash, quantities -- and who made
it; the fold says what the book is after it. Nothing here judges an entry: whether a fill's price
times its quantity is its cash is the venue's business, whether a dividend is recognised on the
ex-date is the accrual's. The ledger checks append order and that the folded state is a valid
account, and nothing else (§5.2: *the ledger checks what the ledger knows*).

**One shape, an origin tag** (§5.2). A fill, a dividend, a split, a subscription all move cash
and quantities in some combination of the same two cells, so a sum type over them would classify
by a fact the ledger already holds. `origin` says what made the entry; `detail` carries what that
origin wants remembered, as portable scalars, so the record can hold it.

**Not fill-only** (§5.3). Encoding a dividend as a zero-quantity buy keeps the account's numbers
right and corrupts every count that reads fills as fills: turnover, fill rate, cost analysis. So
the fill origin is one of several rather than the only one, and the run's fill table is written
from fill entries alone.

Record `211`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from vqapr.domain.fills import Fill, FillBatch
from vqapr.domain.orders import OrderBatch
from vqapr.domain.values import require_tz_aware

__all__ = ["FILL_ORIGIN", "LedgerEntry", "fill_entries"]

FILL_ORIGIN = "fill"
"""The origin of an entry a venue's fill made. The one origin the market clock produces today;
ACCRUE (design §7.3) is where the next ones will come from."""


def _finite(value: object, *, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One appended fact: what it changed, when, and what made it.

    `cash` and `positions` are DELTAS. Either may be zero -- a refused fill changes nothing and is
    still a fact the run has to be able to show afterwards (its `reason` is in `detail`), and a
    stock split changes quantities and no cash. `detail` is the origin's own: for a fill, the
    requested quantity, the price, the cost and the category it was charged as.
    """

    at: datetime
    cash: Decimal
    positions: Mapping[str, Decimal]
    origin: str
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_tz_aware(self.at, name="at")
        _finite(self.cash, name="cash")
        if not isinstance(self.positions, Mapping):
            raise TypeError("positions must be a mapping of instrument deltas")
        deltas: dict[str, Decimal] = {}
        for instrument_id, quantity in self.positions.items():
            if not isinstance(instrument_id, str) or not instrument_id:
                raise ValueError("position instrument ids must be non-empty strings")
            deltas[instrument_id] = _finite(quantity, name=f"positions[{instrument_id!r}]")
        object.__setattr__(self, "positions", MappingProxyType(deltas))
        if not isinstance(self.origin, str) or not self.origin:
            raise ValueError("origin must be a non-empty string")
        if not isinstance(self.detail, Mapping):
            raise TypeError("detail must be a mapping")
        object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))


def fill_entries(
    at: datetime, fills: FillBatch, orders: OrderBatch | None = None
) -> tuple[LedgerEntry, ...]:
    """The entries one fill batch makes, one per fill, in the batch's own order.

    The producer's half of §5.2: the venue said what each fill dealt at what price and cost, and
    `Fill` already proved those agree with each other. The ledger is handed the resulting deltas
    and the facts a reader of `vqapr.fill` needs, and asks nothing further.

    `orders` is the batch the fills answer. Each fill's `sized_quantity` -- what its weight sized
    to before the planner cut buys to the cash -- is read from it here, once, for every venue
    (record `261`); without it the value is `None`.
    """
    if not isinstance(fills, FillBatch):
        raise TypeError("fills must be a FillBatch")
    sized = (
        {}
        if orders is None
        else {request.instrument_id: request.sized_quantity for request in orders.requests}
    )
    return tuple(_fill_entry(at, fill, sized.get(fill.instrument_id)) for fill in fills.fills)


def _fill_entry(at: datetime, fill: Fill, sized: Decimal | None) -> LedgerEntry:
    dealt = fill.dealt_quantity
    return LedgerEntry(
        at=at,
        cash=fill.cash_delta,
        positions={fill.instrument_id: dealt} if dealt != 0 else {},
        origin=FILL_ORIGIN,
        detail={
            "instrument": fill.instrument_id,
            "requested_quantity": str(fill.requested_quantity),
            "sized_quantity": None if sized is None else str(sized),
            "dealt_quantity": str(dealt),
            "price": None if fill.price is None else str(fill.price),
            "commission": str(fill.cost.commission),
            "tax": str(fill.cost.tax),
            "reason": None if fill.reason is None else str(fill.reason),
            "kind": None if fill.kind is None else str(fill.kind),
        },
    )
