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
from decimal import Decimal

from pydantic import field_validator

from vqapr.domain.instruments import Instrument, InstrumentKind
from vqapr.domain.instruments import instruments as build_instruments
from vqapr.domain.values import Side, side_of
from vqapr.exchange.costs import FREE, FillCost, SideCost
from vqapr.exchange.execution_table import accepted_requests, requested_rows, validate_requests
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.exchange.listings import (
    ExchangeRulesView,
    ExecutionFieldRequirement,
    ListingAccess,
    TradeRule,
    TradeTerms,
    trade_rules_by_kind,
)
from vqapr.exchange.venue import Exchange, ExecutionCall
from vqapr.orders.batches import OrderRequest

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

    The base rule's checks are inherited with its validators; only the regime is checked here.
    """

    price_limit_rate: Decimal | None = None

    def __init__(
        self,
        instrument_id: str,
        quantity_step: Decimal,
        minimum_quantity: Decimal,
        fractional_allowed: bool,
        access: ListingAccess = ListingAccess.LONG_ONLY,
        buy: SideCost = FREE,
        sell: SideCost = FREE,
        price_limit_rate: Decimal | None = None,
    ) -> None:
        # Spelled out rather than inherited so the regime field is a named parameter: a caller
        # and a type checker both see it, instead of it travelling as an anonymous keyword.
        super().__init__(
            instrument_id,
            quantity_step,
            minimum_quantity,
            fractional_allowed,
            access,
            buy,
            sell,
            price_limit_rate=price_limit_rate,
        )

    @field_validator("price_limit_rate")
    @classmethod
    def _fraction(cls, value: Decimal | None) -> Decimal | None:
        # Finite is pydantic's check; the open interval is this regime's.
        if value is not None and not (0 < value < 1):
            raise ValueError("price_limit_rate must be a finite fraction between 0 and 1")
        return value

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
        if base is None:
            return True
        band = self.limit_band(base)
        if band is None:
            return True
        lower, upper = band
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
) -> dict[str, KrxTradeRule]:
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
) -> tuple[dict[str, KrxTradeRule], dict[str, Instrument]]:
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


class KrxExchange(Exchange):
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
            return (ExecutionFieldRequirement(price=BASE_PRICE, feature="price_limit"),)
        return ()

    @property
    def rules(self) -> ExchangeRulesView:
        """The read-only projection order planning consumes."""
        return self._rules

    @property
    def listings(self) -> Mapping[str, TradeRule]:
        return self._rules.listings

    def execute(self, call: ExecutionCall) -> FillBatch:
        orders, account, snapshot = call.orders, call.account, call.snapshot
        requests = accepted_requests(orders, account, snapshot)
        rows = requested_rows(snapshot, requests)
        rules = call.rules
        validate_requests(rules, requests, rows, account)
        # Sells settle before buys, and the cash they raise is carried across the batch. A desk
        # funds a rotation from the sleeve it is rotating out of; filling in instrument order
        # instead judges a batch unaffordable that would have executed comfortably.
        #
        # Costs are charged out of the same purse. `plan_orders` sizes against NAV and the
        # commission is charged at the fill, so a batch that exactly spends its cash ends
        # overdrawn once charged -- issue `002`. What is left when the money runs out is a partial
        # fill: `Fill` already carries `requested_quantity` apart from `dealt_quantity`, so the
        # shape exists and nothing downstream has to learn a new one.
        #
        # KRX only, and structurally so. This needs whole-share rounding to leave a residual the
        # plan could not size away; the academic profile is fractional, sizes exactly to its cash,
        # and has no cause to model.
        purse = account.cash
        fills: list[Fill] = []
        for request in sorted(requests, key=self._settlement_order):
            row = rows.get(request.instrument_id)
            if row is None:
                fills.append(
                    Fill.zero_dealt(
                        request.instrument_id, request.delta_quantity, ZeroDealtReason.ABSENT
                    )
                )
                continue
            if request.delta_quantity == 0:
                fills.append(
                    Fill.zero_dealt(request.instrument_id, Decimal("0"), ZeroDealtReason.NO_TRADE)
                )
                continue
            if not row.is_tradable:
                fills.append(
                    Fill.zero_dealt(
                        request.instrument_id, request.delta_quantity, ZeroDealtReason.NONTRADABLE
                    )
                )
                continue
            side = side_of(request.delta_quantity)
            assert side is not None
            price = row.price
            if price is None:
                # `requested_rows` refuses a tradable row without a positive finite price before
                # any batch reaches here, so a missing one is a broken snapshot, not a market fact.
                raise RuntimeError(
                    f"tradable execution row for {request.instrument_id!r} carries no price"
                )
            rule = rules.listing(request.instrument_id)
            if isinstance(rule, KrxTradeRule) and not rule.permits_side_at(
                side, price, row.reference
            ):
                # Limit-up leaves no seller, limit-down no buyer. A market fact for one session,
                # so it is typed zero-dealt evidence rather than a refusal of the batch.
                fills.append(
                    Fill.zero_dealt(
                        request.instrument_id, request.delta_quantity, ZeroDealtReason.NONTRADABLE
                    )
                )
                continue
            # The notional is no longer computed here: `_affordable` decides the quantity first,
            # and charging the requested size rather than the dealt one is what a partial fill
            # must not do.
            dealt, cost = self._affordable(request, price, side, purse, rules)
            if dealt == 0:
                fills.append(
                    Fill.zero_dealt(
                        request.instrument_id, request.delta_quantity, ZeroDealtReason.UNFUNDED
                    )
                )
                continue
            fill = Fill(
                request.instrument_id,
                request.delta_quantity,
                dealt,
                price,
                cost=cost,
                kind=rules.stamped_kind(request.instrument_id),
            )
            purse += fill.cash_delta
            fills.append(fill)
        # Back into identity order. Settlement order is an execution detail; the fill table is
        # read by run records and comparisons that depend on a stable order (invariant 1).
        fills.sort(key=lambda fill: fill.instrument_id)
        return FillBatch(tuple(fills), account.version)

    @staticmethod
    def _settlement_order(request: OrderRequest) -> tuple[int, str]:
        """Sells first, then buys, each group in identity order.

        Deterministic within each group, so a batch executes identically on every replay -- the
        ordering decides which buy goes unfunded when the money runs out, and a run that answered
        differently on a rerun would make the shortfall unreproducible.
        """
        return (0 if request.delta_quantity < 0 else 1, request.instrument_id)

    def _affordable(
        self,
        request: OrderRequest,
        price: Decimal,
        side: Side,
        purse: Decimal,
        rules: ExchangeRulesView,
    ) -> tuple[Decimal, FillCost]:
        """How much of this request the account can pay for at ``price``, and what that costs.

        A sale always fills in full: it RAISES cash, and its own commission and tax come out of the
        proceeds rather than out of the balance.

        A buy is clipped to what the purse holds, in whole shares, with the commission included in
        the affordability test rather than charged afterwards. Solved by shrinking rather than by
        dividing, because the rate applies to the notional and the notional depends on the
        quantity: `q * price * (1 + rate) <= purse` gives the bound directly, and the quantity step
        then rounds it down to something the listing permits.
        """
        requested = abs(request.delta_quantity)
        if side is Side.SELL:
            return request.delta_quantity, rules.charge(
                side, requested * price, request.instrument_id
            )

        rate = rules.charge(side, price, request.instrument_id).total / price
        step = rules.listing(request.instrument_id).quantity_step
        affordable = purse / (price * (Decimal(1) + rate))
        capped = min(requested, (affordable // step) * step)
        if capped <= 0:
            return Decimal("0"), rules.charge(side, Decimal("0"), request.instrument_id)
        return capped, rules.charge(side, capped * price, request.instrument_id)
