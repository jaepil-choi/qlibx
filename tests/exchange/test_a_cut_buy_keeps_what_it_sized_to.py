"""A buy the planner cut to the cash keeps, in the record, what its weight sized to.

Report 2026-09-11 (`docs/issues/report-2026-09-11-the-krx-settlement-order-is-not-written-where-
an-agent-reads-so-an-agent-reported-vqapr-does-not-apply-it.md`): an agent comparing
`requested_quantity` with its own `trunc(w x NAV / price - held)` saw smaller numbers and no
reason, because the request was recorded after the cut and nothing marked it. The owner ruled
(2026-09-11) that `vqapr.fill` carries the pre-cut quantity beside it (record `261`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.costs import SideCost
from vqapr.domain.fills import Fill, FillBatch
from vqapr.domain.ledger import fill_entries
from vqapr.exchange.listings import ExchangeRulesView, ListingAccess, TradeRule
from vqapr.exchange.planning import plan_orders
from vqapr.portfolio.budgets import Budget, PortfolioDirection

_AT = datetime(2024, 1, 2, 15, 30, tzinfo=UTC)
_BUDGET = Budget(PortfolioDirection.LONG_ONLY, Decimal(0), Decimal(1), Decimal(0), Decimal(1))
SMALL, BIG = "A000001", "Z999999"


def _batch():
    """Two whole-share buys that together overrun the cash by their commission."""
    rules = ExchangeRulesView(
        "whole",
        {
            name: TradeRule(
                name,
                Decimal(1),
                Decimal(1),
                False,
                ListingAccess.LONG_ONLY,
                SideCost(commission_rate=Decimal("0.0003")),
                SideCost(),
            )
            for name in (SMALL, BIG)
        },
    )
    return plan_orders(
        account=AccountSnapshot(0, Decimal(1_000_000), {}),
        execution_time_nav=Decimal(1_000_000),
        prices={SMALL: Decimal(10_000), BIG: Decimal(10_000)},
        weight_targets={SMALL: Decimal("0.1"), BIG: Decimal("0.9")},
        cash_target=Decimal(0),
        budget=_BUDGET,
        rules=rules,
    )


def test_the_cut_buy_requests_less_than_it_sized_to() -> None:
    requests = {request.instrument_id: request for request in _batch().requests}

    assert (requests[SMALL].sized_quantity, requests[SMALL].delta_quantity) == (10, 9)
    assert (requests[BIG].sized_quantity, requests[BIG].delta_quantity) == (90, 90), (
        "a buy funded in full sized to exactly what it requests"
    )


def test_the_fill_entry_carries_the_sized_quantity_from_its_order() -> None:
    batch = _batch()
    fills = FillBatch(
        (
            Fill(SMALL, Decimal(9), Decimal(9), Decimal(10_000)),
            Fill(BIG, Decimal(90), Decimal(90), Decimal(10_000)),
        ),
        0,
    )

    entries = fill_entries(_AT, fills, batch)

    assert [entry.detail["sized_quantity"] for entry in entries] == ["10", "90"]
    assert [entry.detail["requested_quantity"] for entry in entries] == ["9", "90"]


def test_without_its_orders_a_fill_entry_says_nothing_was_sized() -> None:
    fills = FillBatch((Fill(SMALL, Decimal(9), Decimal(9), Decimal(10_000)),), 0)

    (entry,) = fill_entries(_AT, fills)

    assert entry.detail["sized_quantity"] is None
