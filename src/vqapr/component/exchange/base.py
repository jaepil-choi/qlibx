"""The Exchange role: a tool on the market clock that fills an order batch.

An Exchange is called at the instant a pending intent targets, with an `ExecutionCall`: the order
batch, the execution table read exactly at that instant, the account the orders are sized against,
the project's instrument dictionary, and its own rules bound to that dictionary. It returns the
fills. How it fills is entirely the venue's own business; what a venue models is its `settings`, a
mapping it declares and the run records beside its fingerprint.

The checks every profile makes about a call -- which requests the snapshot can answer, the rows they
name, the requests against the listings (`accepted_requests`, `requested_rows`, `validate_requests`)
-- live here once; a profile owns only how it fills. Shipped profiles are beside this module
(`academic.py`, `krx.py`) and enter through the same door as a user's.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from vqapr.component.base import Tool
from vqapr.data.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.domain.account import AccountSnapshot
from vqapr.domain.fill import (
    FillBatch,
)
from vqapr.domain.instants import require_tz_aware
from vqapr.domain.instrument import InstrumentRoster
from vqapr.domain.listing import (
    ExchangeRulesView,
    ExecutionFieldRequirement,
    side_of,
)
from vqapr.domain.memory import ModelMemory
from vqapr.domain.order import OrderBatch
from vqapr.domain.wiring import Role

__all__ = [
    "Exchange",
    "ExecutionCall",
    "accepted_requests",
    "requested_rows",
    "validate_requests",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionCall:
    """What an Exchange is handed at a market-clock instant (design §6.1):

        the order batch            `orders`
        the market state then      `snapshot` -- the execution table read exactly at `at`
        the account snapshot       `account`
        the instrument dictionary  `instruments` -- what every id the batch or the book names IS

    and its own `rules`, bound to that dictionary. The dictionary is the project's roster, whole
    (design §6.4: it has no time axis, so it is read entire rather than through a window); a
    fill's category and its cost come from it rather than from a venue's copy. `rules` may be
    handed in unbound -- the venue's own view -- and is bound here; a view already bound to a
    different dictionary is refused rather than silently rebound.
    """

    at: datetime
    orders: OrderBatch
    account: AccountSnapshot
    snapshot: ExactExecutionSnapshot
    instruments: InstrumentRoster
    rules: ExchangeRulesView

    def __post_init__(self) -> None:
        require_tz_aware(self.at, name="at")
        if not isinstance(self.instruments, InstrumentRoster):
            raise TypeError("instruments must be an InstrumentRoster")
        if not isinstance(self.rules, ExchangeRulesView):
            raise TypeError("rules must be an ExchangeRulesView")
        bound = self.rules.registry
        if bound is None:
            object.__setattr__(self, "rules", self.rules.with_registry(self.instruments))
        elif bound.instruments != self.instruments.instruments:
            raise ValueError(
                "rules are bound to a different instrument dictionary than the call carries"
            )


class Exchange(Tool):
    """The execution extension point: a tool on the market clock that fills an order batch.

    Deliberately small. A venue declares what it trades (`rules`) and, when its regime needs a
    second price beside the trade price, which execution-table field that is
    (`execution_requirements`); it is called with an `ExecutionCall` and returns a `FillBatch`.
    A user subclasses one of the shipped profiles and may add listings and costs; `load_exchange`
    refuses a subclass that replaces `execute`, because the realism claim of a profile is its
    fill semantics.
    """

    exchange_id: str
    ROLE: ClassVar[Role] = Role.EXCHANGE

    @property
    @abstractmethod
    def rules(self) -> ExchangeRulesView:
        """The venue's own quantity and cost rules, read by order planning."""

    @property
    def settings(self) -> Mapping[str, ModelMemory]:
        """What this venue models, as data (design §6.1): its regimes and switches, declared.

        The schema is the venue's own -- KRX says whether its price band is on and what it
        charges; another venue says something else -- and the framework knows only that a venue
        has settings. They are recorded in `strategy.json` under `exchange.settings`, so which of
        two configurations a past run measured is read from the record rather than recovered by
        opening the venue's source at its digest. Strict JSON (`ModelMemory`); the loader refuses
        anything else. Empty by default.
        """
        return {}

    def execution_requirements(self) -> tuple[ExecutionFieldRequirement, ...]:
        """The execution-table prices this venue needs beside the trade price. None by default."""
        return ()

    @abstractmethod
    def execute(self, call: ExecutionCall) -> FillBatch:
        """Fill the batch at the call's instant, from the call's rows, under the call's rules."""


def requested_rows(
    snapshot: ExactExecutionSnapshot, requests: Sequence[Any]
) -> dict[str, ExactExecutionRow]:
    """The snapshot rows a batch asked about, checked against the snapshot's own contract.

    Lifted here from both execution profiles, where it stood twice byte for byte under two names
    (`AcademicExchange._validate_snapshot` and `KrxExchange._rows`). Two copies of one contract
    check drift the first time only one is edited, and issue `002` named that as the thing most
    likely to go wrong between the profiles.

    A FUNCTION rather than a shared base class, deliberately. What this checks is a property of
    `ExactExecutionSnapshot` -- no duplicate requested instrument, a boolean tradability, a
    positive finite price when tradable -- and none of it is venue policy. The profiles genuinely
    differ on quantity, cost, shorting and account access, and a base class inviting those to be
    shared is what issue `002` warns against. `load_exchange` also refuses a subclass whose
    `execute` is not its profile's, so a shared `execute` would blur which semantics a subclass
    claims.
    """
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


def validate_requests(
    rules: ExchangeRulesView,
    requests: Sequence[Any],
    rows: Mapping[str, ExactExecutionRow],
    account: Any,
) -> None:
    """Refuse a batch whose requests the venue's own listings do not permit.

    The third and last piece lifted out of both profiles (after `requested_rows` and
    `accepted_requests`, issue `002`): the request loop that stood as
    `AcademicExchange._validate_rules` and `KrxExchange._validate`. Same six checks -- a finite
    quantity, a listing, a positive finite selected price on a tradable row, a side, the position
    change, the quantity -- with the last two in opposite order and under different words. The
    `permits_quantity` docstring records the bug that drift produced: one profile stopped checking
    the minimum and the other did not, because the check was spelled twice.

    Every question here is put to the LISTING (`TradeRule.permits_position`,
    `TradeRule.permits_quantity`); this only walks the batch and phrases the refusal. Position is
    checked before quantity, so an order that is both a short and off the unit is refused as the
    short: the access class is the venue's standing declaration about the instrument, the unit
    is a detail of this size.
    """
    for request in requests:
        quantity = request.delta_quantity
        if not quantity.is_finite():
            raise ValueError(f"invalid requested quantity for {request.instrument_id!r}")
        rule = rules.listing(request.instrument_id)
        row = rows.get(request.instrument_id)
        if (
            row is not None
            and row.is_tradable
            and (not request.execution_price.is_finite() or request.execution_price <= 0)
        ):
            raise ValueError(f"invalid selected price for {request.instrument_id!r}")
        if side_of(quantity) is None:
            continue
        held = account.positions.get(request.instrument_id, Decimal("0"))
        if not rule.permits_position(held, quantity):
            if rule.tradable:
                # The listing's own declaration, not a rule bolted onto a profile: selling a held
                # position is always fine, and only a resulting short is refused.
                raise ValueError(
                    f"{rule.access.value} listing does not support short selling "
                    f"{request.instrument_id!r}"
                )
            raise ValueError(
                f"{rule.access.value} listing does not permit this position change for "
                f"{request.instrument_id!r}"
            )
        if not rule.permits_quantity(abs(quantity)):
            unit = "divisible" if rule.fractional_allowed else f"step {rule.quantity_step}"
            raise ValueError(
                f"quantity violates listing rule for {request.instrument_id!r}: {abs(quantity)} "
                f"(minimum {rule.minimum_quantity}, {unit})"
            )


def accepted_requests(orders: Any, account: Any, snapshot: Any) -> tuple[Any, ...]:
    """The batch's requests in stable identity order, after the checks every profile makes.

    The other half of the duplication issue `002` measured: eleven lines standing byte for byte in
    both profiles' `execute`. Types, the account-version match, and one request per instrument are
    preconditions on the CALL rather than decisions about a venue, so they belong beside the types
    they check.

    Returns the sorted requests instead of validating in place, because sorting is the last of the
    shared steps and every caller needs its result -- returning it is what stops the sort itself
    from being the twelfth duplicated line.
    """
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
    return requests
