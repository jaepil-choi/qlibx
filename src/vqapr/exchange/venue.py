"""Closed academic execution policy at the Exchange extension boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Protocol

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.values import side_of
from vqapr.exchange.execution_table import (
    ExactExecutionSnapshot,
    accepted_requests,
    requested_rows,
    validate_requests,
)
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.exchange.listings import ExchangeRulesView, TradeRule
from vqapr.orders.batches import OrderBatch


class Exchange(Protocol):
    """The deliberately small execution extension boundary.

    Before changing a profile, read `docs/issues/002-execution-profiles-share-no-base.md`. What
    every profile checks about a call -- the batch, the snapshot rows, the requests against the
    listings -- lives once in `execution_table` (`accepted_requests`, `requested_rows`,
    `validate_requests`); a profile owns only how it fills. The academic profile still does not
    sequence a batch: sells do not fund buys and it cannot produce a partial fill, which is
    correct for a fractional, zero-friction venue and is what `KrxExchange` adds.
    """

    exchange_id: str

    @property
    def rules(self) -> ExchangeRulesView:
        """The venue's own quantity and cost rules, read by order planning."""
        ...

    def execute(
        self, orders: OrderBatch, account: AccountSnapshot, snapshot: ExactExecutionSnapshot
    ) -> FillBatch: ...


@dataclass(frozen=True, slots=True)
class AcademicExchange:
    """Zero-friction, full-fill execution for declared academic listings."""

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
        object.__setattr__(self, "listings", copied)

    terms_by_kind: ClassVar[Mapping[object, object] | None] = None
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
    def rules(self) -> ExchangeRulesView:
        """Academic listings with no declared cost band, so this profile charges nothing.

        A subclass may declare one, either by giving each listing its own `buy`/`sell` or -- when
        the rate follows the category -- by setting `terms_by_kind`. `execute` charges whatever
        this returns, so a subclass that adds a cost band gets it applied without replacing any
        matching behaviour.

        The venue never DECLARES a roster -- there is no constructor parameter for one, so an
        author has no channel to state a category. What it may hold is one handed to it at run
        assembly, which `_registry` carries and this view borrows.

        Rebuilt per access rather than cached because a subclass overriding this property is how a
        cost band is added, and a cached view would freeze the base profile's answer.
        """
        return ExchangeRulesView(
            self.exchange_id,
            self.listings,
            getattr(self, "_registry", None),
            type(self).terms_by_kind,
        )

    def execute(
        self, orders: OrderBatch, account: AccountSnapshot, snapshot: ExactExecutionSnapshot
    ) -> FillBatch:
        """Validate global prerequisites, then return every order in stable identity order."""
        requests = accepted_requests(orders, account, snapshot)
        rows = requested_rows(snapshot, requests)
        rules = self.rules
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
                fills.append(
                    Fill(
                        request.instrument_id,
                        request.delta_quantity,
                        request.delta_quantity,
                        row.price,
                        cost=rules.charge(
                            side,
                            rules.notional(
                                request.instrument_id, request.delta_quantity, row.price
                            ),
                            request.instrument_id,
                        ),
                        kind=rules.stamped_kind(request.instrument_id),
                    )
                )
        return FillBatch(tuple(fills), account.version)
