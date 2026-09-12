"""The academic execution profile: zero-friction, full-fill execution for declared listings.

Every accepted order fills whole at the call's price with no cost -- frictionless by declaration,
and its settings say so. A subclass may add listings and a cost band (per listing, or per category
through `terms_by_kind`) and gets them charged without replacing any fill behaviour; a subclass that
replaces `execute` is refused at load, because a profile's realism claim is its fill semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar

from vqapr.component.exchange.base import (
    Exchange,
    ExecutionCall,
    accepted_requests,
    requested_rows,
    validate_requests,
)
from vqapr.domain.fill import Fill, FillBatch, ZeroDealtReason
from vqapr.domain.instrument import InstrumentKind
from vqapr.domain.listing import (
    ExchangeRulesView,
    TradeRule,
    TradeTerms,
    side_of,
)
from vqapr.domain.memory import ModelMemory

__all__ = [
    "AcademicExchange",
]


@dataclass(eq=False)
class AcademicExchange(Exchange):
    """Zero-friction, full-fill execution for declared academic listings.

    A plain dataclass rather than a frozen one since record `184`: a Component carries `memory`
    the engine restores and commits, and a frozen instance could not receive it.
    """

    listings: Mapping[str, TradeRule]
    exchange_id: str = "academic"

    def __post_init__(self) -> None:
        if not isinstance(self.exchange_id, str) or not self.exchange_id:
            raise ValueError("exchange_id must be a non-empty string")
        if not isinstance(self.listings, Mapping):
            raise TypeError("listings must be a mapping")
        copied = dict(self.listings)
        for instrument_id, rule in copied.items():
            if not isinstance(rule, TradeRule) or instrument_id != rule.instrument_id:
                raise ValueError("each listing key must match its TradeRule instrument_id")
        self.listings = copied

    terms_by_kind: ClassVar[Mapping[InstrumentKind, TradeTerms] | None] = None
    """Per-category terms, for a subclass whose rate depends on WHAT an instrument is.

    Declare it and the charge is resolved per fill from the project's registered roster, the same
    way `KrxExchange` does. Leave it `None` -- the default, and what the academic profile is -- and
    each listing's own `buy`/`sell` are charged.

    This is the channel a category-driven venue should use instead of baking a rate into each
    `TradeRule`. Baking it in means holding a second copy of a fact the project owns, and the two
    can then disagree: a fill records the category the roster declared while the money follows the
    venue's own idea of it (issue 013). A class attribute rather than a constructor parameter,
    because it is a property of the VENUE TYPE -- what KRX charges an ETF is not something one
    instance of a KRX venue decides differently from another.
    """

    @property
    def settings(self) -> Mapping[str, ModelMemory]:
        """Frictionless by declaration: no cost, no band, every accepted order filled whole."""
        return {"profile": "academic", "costs": "none", "partial_fills": "never"}

    @property
    def rules(self) -> ExchangeRulesView:
        """Academic listings with no declared cost band, so this profile charges nothing.

        A subclass may declare one, either by giving each listing its own `buy`/`sell` or -- when
        the rate follows the category -- by setting `terms_by_kind`. `execute` charges whatever
        the call's rules say, and the handler builds those from this view, so a subclass that adds
        a cost band gets it applied without replacing any matching behaviour.

        The venue never DECLARES a roster -- there is no constructor parameter for one, so an
        author has no channel to state a category. The roster reaches a fill as
        `ExecutionCall.instruments`, and `call.rules` is this view bound to it; this view is
        unbound.

        Rebuilt per access rather than cached because a subclass overriding this property is how a
        cost band is added, and a cached view would freeze the base profile's answer.
        """
        return ExchangeRulesView(
            self.exchange_id,
            self.listings,
            None,
            type(self).terms_by_kind,
        )

    def execute(self, call: ExecutionCall) -> FillBatch:
        """Validate global prerequisites, then return every order in stable identity order."""
        orders, account, snapshot = call.orders, call.account, call.snapshot
        requests = accepted_requests(orders, account, snapshot)
        rows = requested_rows(snapshot, requests)
        rules = call.rules
        validate_requests(rules, requests, rows, account)

        fills: list[Fill] = []
        for request in requests:
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
            else:
                side = side_of(request.delta_quantity)
                assert side is not None
                # `requested_rows` refused a tradable row without a finite positive price.
                price = row.price
                assert price is not None
                fills.append(
                    Fill(
                        request.instrument_id,
                        request.delta_quantity,
                        request.delta_quantity,
                        price,
                        cost=rules.charge(
                            side,
                            rules.notional(request.instrument_id, request.delta_quantity, price),
                            request.instrument_id,
                        ),
                        kind=rules.stamped_kind(request.instrument_id),
                    )
                )
        return FillBatch(tuple(fills), account.version)
