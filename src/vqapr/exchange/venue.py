"""The Exchange: the Component that reads the execution table at a fill instant and executes orders.

An Exchange is a Component like the other three (owner ruling, 2026-09-08; record `184`): it is
called back on an event -- the due event a callback minted -- with that event's instant, it is
handed a bounded view of what it may read, it carries `memory` between callbacks, and it returns
one judgment, the fills. What makes it different is not that it reads one instant (a strategy can
read one row too) but what it is handed beside the data: **the order batch it must execute**, and
the account those orders are sized against. That list is on `ExecutionCall`, and nowhere else.

Before this the venue received three positional arguments and the framework reached into it to
plant the project's roster (`object.__setattr__(venue, "_registry", ...)`), because `execute`'s
signature was not the framework's to change. With a `Call` the roster rides in as
`call.instruments` -- the instrument dictionary design §6.1 names as the fourth thing a venue is
handed -- and `call.rules` is the venue's own view bound to it. The venue stores nothing the run
handed it.

**The contract is narrow, and the venue's inside is its own** (design §6.1). What a venue models
-- which costs, which regimes, on or off -- is the venue's *settings*, a mapping it declares and
the run records beside its fingerprint. The framework knows only that a venue has settings.

The academic profile is defined here. Before changing a profile, read
`docs/issues/archive/002-execution-profiles-share-no-base.md`: what every profile checks about a
call -- the batch, the snapshot rows, the requests against the listings -- lives once in
`execution_table` (`accepted_requests`, `requested_rows`, `validate_requests`); a profile owns only
how it fills.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from vqapr.authoring import Tool
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.domain.instruments import InstrumentKind, InstrumentRoster
from vqapr.domain.orders import OrderBatch
from vqapr.domain.values import ModelMemory, require_tz_aware, side_of
from vqapr.domain.wiring import Role
from vqapr.exchange.execution_table import (
    ExactExecutionSnapshot,
    accepted_requests,
    requested_rows,
    validate_requests,
)
from vqapr.exchange.listings import (
    ExchangeRulesView,
    ExecutionFieldRequirement,
    TradeRule,
    TradeTerms,
)


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
