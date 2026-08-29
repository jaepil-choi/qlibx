"""KRX execution profile.

This profile implements a declared, deliberately partial set of KRX rules. It claims exactly what
it implements and nothing else (PRD 6.3):

Implemented
    whole-share quantity unit, brokerage commission on both sides, sale tax on sells only and only
    for the categories that owe it, halted instruments producing typed zero-dealt results, refusal
    of any order that would open or deepen a short position, and full execution of the remainder at
    the exact selected price.

Not implemented, and therefore not claimed
    price ticks, daily price limits, auction microstructure, queue position, partial fills from
    liquidity or participation limits, borrow and locate for short sales, margin, and any intraday
    behaviour. Costs other than the declared commission and tax are absent, not zero by measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.enums import Side, side_of
from vqapr.domain.instruments import Instrument, InstrumentKind
from vqapr.domain.instruments import instruments as build_instruments
from vqapr.exchange.costs import SideCost
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.exchange.listings import (
    ExchangeRulesView,
    ExecutionFieldRequirement,
    ListingAccess,
    TradeRule,
    TradeTerms,
    trade_rules_by_kind,
)
from vqapr.orders.batches import OrderBatch, OrderRequest

COMMISSION_RATE = Decimal("0.0003")
"""Brokerage commission charged on both sides."""

SALE_TAX_RATE = Decimal("0.002")
"""Securities transaction tax charged on sells only."""

SHARE_UNIT = Decimal("1")
"""KRX equities trade in whole shares."""


PRICE_LIMIT_RATE = Decimal("0.30")
"""KRX applies one rate to every listed share and ETF: the base price plus or minus 30%."""

BASE_PRICE = "base"
"""The semantic execution price a price-limit venue requires: the session's base price."""


@dataclass(frozen=True, slots=True)
class KrxTradeRule(TradeRule):
    """A KRX rule, which carries one regime the base rule has no field for.

    ``price_limit_rate`` is the band width as a fraction of the session base price. ``None`` means
    the venue is not applying limits to this instrument -- an explicit off, which is a different
    declaration from a venue that has no concept of limits at all, and both appear in the
    fingerprint.

    The rate lives on the *rule* rather than the venue because it is per-instrument in practice:
    KRX applies one rate today, but a managed-issue regime narrows it for named issues, and China
    runs 10% on the main boards against 20% on ChiNext and STAR. A venue-level constant could not
    express either.
    """

    price_limit_rate: Decimal | None = None

    def __post_init__(self) -> None:
        # `slots=True` rebuilds the class, so the zero-argument `super()` closure cell points at
        # the pre-slots class and raises. The explicit form is required for a slotted subclass.
        TradeRule.__post_init__(self)
        rate = self.price_limit_rate
        if rate is None:
            return
        if not isinstance(rate, Decimal):
            raise TypeError("price_limit_rate must be a Decimal or None")
        if not rate.is_finite() or not (0 < rate < 1):
            raise ValueError("price_limit_rate must be a finite fraction between 0 and 1")

    def limit_band(self, base: Decimal) -> tuple[Decimal, Decimal] | None:
        """The inclusive ``(lower, upper)`` prices this instrument may trade at today."""
        if self.price_limit_rate is None:
            return None
        return (
            base * (Decimal("1") - self.price_limit_rate),
            base * (Decimal("1") + self.price_limit_rate),
        )

    def permits_side_at(self, side: Side, price: Decimal, base: Decimal | None) -> bool:
        """Whether this side may trade at ``price`` given today's base price.

        At the upper limit there is no seller left, so a buy cannot fill; at the lower limit there
        is no buyer, so a sell cannot. The position rule is unchanged -- this is a market fact for
        one session, not a standing venue permission.
        """
        if self.price_limit_rate is None or base is None:
            return True
        lower, upper = self.limit_band(base)
        if side is Side.BUY:
            return price < upper
        return price > lower


def krx_stock_terms(
    commission_rate: Decimal = COMMISSION_RATE,
    sale_tax_rate: Decimal = SALE_TAX_RATE,
) -> TradeTerms:
    """Whole shares, commission both sides, securities transaction tax on sells.

    ``LONG_ONLY`` is this profile's own claim, not a market fact: KRX has a regulated short-sale
    regime, and modelling it needs borrow, locate and recall, none of which this profile
    implements. Declaring ``SIGNED`` here would claim a realism it has not shown.
    """
    return TradeTerms(
        quantity_step=SHARE_UNIT,
        minimum_quantity=SHARE_UNIT,
        fractional_allowed=False,
        access=ListingAccess.LONG_ONLY,
        buy=SideCost(commission_rate, Decimal("0")),
        sell=SideCost(commission_rate, sale_tax_rate),
    )


def krx_etf_terms(commission_rate: Decimal = COMMISSION_RATE) -> TradeTerms:
    """Whole units, commission both sides, and **no sale tax** -- KRX exempts ETFs.

    The exemption is real and material. An enhanced-index fund holds an ETF sleeve precisely to
    track the index cheaply, and charging that sleeve the share tax overstates its cost by the
    full tax rate on every unit of sleeve turnover.
    """
    return TradeTerms(
        quantity_step=SHARE_UNIT,
        minimum_quantity=SHARE_UNIT,
        fractional_allowed=False,
        access=ListingAccess.LONG_ONLY,
        buy=SideCost(commission_rate, Decimal("0")),
        sell=SideCost(commission_rate, Decimal("0")),
    )


KRX_TERMS: Mapping[InstrumentKind, TradeTerms] = {
    InstrumentKind.STOCK: krx_stock_terms(),
    InstrumentKind.ETF: krx_etf_terms(),
}
"""The two categories KRX trades. A factor or an index is simply not listed here."""


def krx_listings(
    instrument_ids: Sequence[str],
    *,
    price_limits: bool = True,
) -> dict[str, TradeRule]:
    """KRX's trading facts for a set of ids, needing no categories at all.

    A rule says how an instrument TRADES: whole shares, a minimum of one, long-only, and whether
    the limit-up/limit-down band applies. Those are the venue's own facts and they are identical
    across every category KRX lists -- `KRX_TERMS`' two entries differ only in `buy`/`sell`.

    What an instrument COSTS is therefore not built here. It is resolved per fill from `KRX_TERMS`
    against the category the project's registered roster declares, so this function has no reason
    to ask which instrument is which, and a venue built from it holds no category to disagree with
    the roster (issue 013).

    This is what :func:`krx_rules` should have been. That function still exists for callers holding
    a `{id: kind}` mapping already, but its categories no longer decide anything a run charges.
    """
    rate = PRICE_LIMIT_RATE if price_limits else None
    base = KRX_TERMS[InstrumentKind.STOCK]
    return {
        str(instrument_id): KrxTradeRule(
            str(instrument_id),
            base.quantity_step,
            base.minimum_quantity,
            base.fractional_allowed,
            base.access,
            base.buy,
            base.sell,
            price_limit_rate=rate,
        )
        for instrument_id in instrument_ids
    }


def krx_rules(
    universe: Mapping[str, InstrumentKind | str],
    *,
    price_limits: bool = True,
) -> tuple[dict[str, TradeRule], dict[str, Instrument]]:
    """Build KRX's per-instrument terms from ``instrument_id -> kind``.

    The one call that gets the ETF exemption right: a stock pays the sale tax, an ETF does not,
    and neither is named individually.

    Still returns the built instruments as its second element, but a venue no longer accepts them
    -- identity now comes from the project's registered roster. The pair is kept because a caller
    assembling a universe usually wants both, and because discarding it here would silently change
    what nine in-tree call sites unpack.

    ``price_limits=False`` switches off the limit-up/limit-down regime, which is how a user whose
    execution table carries only a trade price still runs here.

    **The categories it takes no longer decide what a run charges.** `ExchangeRulesView.charge`
    resolves the rate from the registered roster, so the per-kind `buy`/`sell` baked into these
    rules is inert. Prefer :func:`krx_listings`, which asks for ids alone; this is kept for callers
    that already hold a `{id: kind}` mapping and want the built instruments back.
    """
    declared = build_instruments(universe)
    rate = PRICE_LIMIT_RATE if price_limits else None
    base = trade_rules_by_kind(declared, KRX_TERMS)
    rules = {
        instrument_id: KrxTradeRule(
            rule.instrument_id,
            rule.quantity_step,
            rule.minimum_quantity,
            rule.fractional_allowed,
            rule.access,
            rule.buy,
            rule.sell,
            price_limit_rate=rate,
        )
        for instrument_id, rule in base.items()
    }
    return rules, declared


def krx_listing(instrument_id: str) -> TradeRule:
    """A whole-share KRX stock rule: buy, sell what you hold, never go short."""
    return KRX_TERMS[InstrumentKind.STOCK].for_instrument(instrument_id)


class KrxExchange:
    """Whole-share KRX execution with declared commission and sale tax, long positions only."""

    exchange_id: str

    def __init__(
        self,
        listings: Mapping[str, TradeRule] | Sequence[str],
        exchange_id: str = "krx",
    ) -> None:
        """Declare what this venue trades -- which ids, and on what terms.

        ``listings`` may be a bare sequence of ids, which get the stock terms, or explicit
        ``TradeRule`` values.

        **It no longer accepts `instruments`.** What an id IS belongs to the project, not to a
        venue: `kind` does not vary by venue, so a venue declaring it was declaring a fact that
        was never its own (issue 008). Removing the parameter removes the channel -- there is now
        no way for a venue author to state a category, correctly or otherwise.

        The bare-sequence form is consequently no longer a bypass. It says only "these are the ids
        I trade", and **the categories come from the roster** -- which this class now delivers
        rather than merely promises. It used to build every listing from the STOCK terms and charge
        from that rule, so an ETF quietly paid a tax KRX exempts while its fill correctly recorded
        `kind: etf` (issue 013).

        The listings still carry a rule each, because a rule says how an instrument TRADES -- whole
        shares, a minimum, a price band -- and those are the venue's own facts. What it COSTS is
        resolved per fill from `KRX_TERMS` against the roster's category, so this venue holds no
        category of its own and has nothing to disagree with.
        """
        resolved: Mapping[str, TradeRule]
        if isinstance(listings, Mapping):
            resolved = dict(listings)
        else:
            resolved = {instrument: krx_listing(instrument) for instrument in listings}
        for instrument_id, rule in resolved.items():
            if not isinstance(rule, TradeRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its TradeRule instrument_id")
            if rule.fractional_allowed:
                raise ValueError(f"KRX listing {instrument_id!r} must not be fractional")
        self.exchange_id = exchange_id
        self._rules = ExchangeRulesView(exchange_id, resolved, terms_by_kind=KRX_TERMS)

    def execution_requirements(self) -> tuple[ExecutionFieldRequirement, ...]:
        """The execution-table prices this venue needs, given what its rules actually declare.

        A requirement appears only when some listed instrument declares a price limit. A venue that
        switched limits off, or never declared a rate, asks for nothing and runs against a table
        carrying only its trade price -- which is the whole point of the switch: a user with close
        prices alone can still execute here.
        """
        if any(
            isinstance(rule, KrxTradeRule) and rule.price_limit_rate is not None
            for rule in self._rules.listings.values()
        ):
            return (ExecutionFieldRequirement(BASE_PRICE, "price_limit"),)
        return ()

    @property
    def rules(self) -> ExchangeRulesView:
        """The read-only projection order planning consumes."""
        return self._rules

    @property
    def listings(self) -> Mapping[str, TradeRule]:
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
        rules = self._rules

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
            rule = rules.listing(request.instrument_id)
            if isinstance(rule, KrxTradeRule) and not rule.permits_side_at(
                side, row.price, row.reference
            ):
                # Limit-up leaves no seller, limit-down no buyer. A market fact for one session,
                # so it is typed zero-dealt evidence rather than a refusal of the batch.
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
            notional = rules.notional(request.instrument_id, request.delta_quantity, row.price)
            fills.append(
                Fill(
                    request.instrument_id,
                    request.delta_quantity,
                    request.delta_quantity,
                    row.price,
                    cost=rules.charge(side, notional, request.instrument_id),
                    kind=rules.stamped_kind(request.instrument_id),
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
            quantity = abs(request.delta_quantity)
            if not rule.permits_quantity(quantity):
                raise ValueError(
                    f"quantity {quantity} is not a whole share for {request.instrument_id!r}"
                )
            held = account.positions.get(request.instrument_id, Decimal("0"))
            if not rule.permits_position(held, request.delta_quantity):
                # The listing's own declaration, not a rule bolted onto this profile: selling a
                # held position is always fine, and only a resulting short is refused.
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
