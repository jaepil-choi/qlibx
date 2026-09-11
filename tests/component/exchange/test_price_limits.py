"""A venue-specific regime, and the switch that lets a user run without the data it needs.

KRX limits a session's price to the base price plus or minus a declared rate. At the upper limit
there is no seller left, so a buy cannot fill; at the lower limit there is no buyer, so a sell
cannot. That rule is the *exchange's*, computed from a number the user already has -- the session
base price -- and never asked of the user as a conclusion.

The switch is the point of the design: a user holding only close prices runs with
``price_limits=False`` and the venue then requires nothing extra. What must never happen is the
third state -- the regime declared, its data absent, and the run quietly producing numbers that
look limit-aware.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.component.exchange.support import execution_call
from vqapr.component.exchange.krx import (
    BASE_PRICE,
    PRICE_LIMIT_RATE,
    KrxExchange,
    KrxTradeRule,
    krx_rules,
)
from vqapr.data.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.domain.account import AccountSnapshot
from vqapr.domain.fill import ZeroDealtReason
from vqapr.domain.instrument import InstrumentRoster
from vqapr.domain.listing import Side
from vqapr.domain.order import OrderBatch, OrderRequest

NAME = "A005930"
BASE = Decimal("10000")
AT = datetime(2026, 8, 21, 6, 30, tzinfo=UTC)


def _venue(*, price_limits: bool = True) -> KrxExchange:
    listings, instruments = krx_rules({NAME: "stock"}, price_limits=price_limits)
    venue = KrxExchange(listings)
    venue._rules = venue.rules.with_registry(InstrumentRoster(instruments))
    return venue


def _snapshot(price: Decimal, reference: Decimal | None) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(
        AT, (ExactExecutionRow(AT, NAME, True, price, reference),), (), (), ()
    )


def _order(delta: Decimal, price: Decimal, held: Decimal = Decimal("0")) -> OrderBatch:
    return OrderBatch(0, (OrderRequest(NAME, held, held + delta, delta, price, None),))


def test_the_band_is_computed_from_the_base_price_and_the_declared_rate() -> None:
    rule = KrxTradeRule(NAME, Decimal("1"), Decimal("1"), False, price_limit_rate=PRICE_LIMIT_RATE)
    assert rule.limit_band(BASE) == (Decimal("7000.00"), Decimal("13000.00"))

    # Limit-up: sellable, not buyable. Limit-down: the reverse. In between, both.
    assert rule.permits_side_at(Side.BUY, Decimal("13000"), BASE) is False
    assert rule.permits_side_at(Side.SELL, Decimal("13000"), BASE) is True
    assert rule.permits_side_at(Side.BUY, Decimal("7000"), BASE) is True
    assert rule.permits_side_at(Side.SELL, Decimal("7000"), BASE) is False
    assert rule.permits_side_at(Side.BUY, BASE, BASE) is True
    assert rule.permits_side_at(Side.SELL, BASE, BASE) is True


def test_a_buy_at_the_upper_limit_is_typed_zero_dealt_not_a_batch_failure() -> None:
    """A market fact for one session, so the rest of the rebalance still executes."""
    venue = _venue()
    account = AccountSnapshot(0, Decimal("100000000"), {})
    fills = venue.execute(execution_call(venue, 
        _order(Decimal("10"), Decimal("13000")), account, _snapshot(Decimal("13000"), BASE)
    ))
    fill = fills.fills[0]
    assert fill.dealt_quantity == 0
    assert fill.reason is ZeroDealtReason.NONTRADABLE
    assert fill.cost.total == Decimal("0")
    assert fill.requested_quantity == Decimal("10"), "the refused size stays visible"


def test_a_sale_at_the_upper_limit_still_fills() -> None:
    """Limit-up blocks buying, not selling -- the position can always be reduced."""
    venue = _venue()
    held = Decimal("100")
    account = AccountSnapshot(0, Decimal("0"), {NAME: held})
    fills = venue.execute(execution_call(venue, 
        _order(Decimal("-60"), Decimal("13000"), held), account, _snapshot(Decimal("13000"), BASE)
    ))
    fill = fills.fills[0]
    assert fill.dealt_quantity == Decimal("-60")
    assert fill.reason is None


def test_switching_the_regime_off_removes_both_the_rule_and_the_requirement() -> None:
    """The user with close prices only: nothing extra is required and nothing is refused."""
    on, off = _venue(), _venue(price_limits=False)

    assert [r.price for r in on.execution_requirements()] == [BASE_PRICE]
    assert off.execution_requirements() == (), "an off regime asks for no data"

    account = AccountSnapshot(0, Decimal("100000000"), {})
    # Same order, same price, no reference available at all.
    blocked = on.execute(execution_call(on, 
        _order(Decimal("10"), Decimal("13000")), account, _snapshot(Decimal("13000"), BASE)
    )).fills[0]
    filled = off.execute(execution_call(off, 
        _order(Decimal("10"), Decimal("13000")), account, _snapshot(Decimal("13000"), None)
    )).fills[0]

    assert blocked.dealt_quantity == 0
    assert filled.dealt_quantity == Decimal("10"), "with limits off the order fills"


def test_the_two_choices_are_different_declarations() -> None:
    """A run must be able to say which of the two it measured."""
    on_rules, _ = krx_rules({NAME: "stock"}, price_limits=True)
    off_rules, _ = krx_rules({NAME: "stock"}, price_limits=False)

    assert on_rules[NAME].price_limit_rate == PRICE_LIMIT_RATE
    assert off_rules[NAME].price_limit_rate is None
    assert on_rules[NAME].declaration_identity != off_rules[NAME].declaration_identity

    on_venue, off_venue = _venue(), _venue(price_limits=False)
    assert on_venue.rules.declaration_identity != off_venue.rules.declaration_identity


def test_a_declared_rate_must_be_a_usable_fraction() -> None:
    for bad in (Decimal("0"), Decimal("1"), Decimal("-0.3")):
        with pytest.raises(ValueError, match="finite fraction"):
            KrxTradeRule(NAME, Decimal("1"), Decimal("1"), False, price_limit_rate=bad)
    # Strict pydantic: a float is not a Decimal, and the refusal is a `ValidationError`.
    with pytest.raises(ValueError, match="Decimal"):
        KrxTradeRule(NAME, Decimal("1"), Decimal("1"), False, price_limit_rate=0.3)


def test_a_missing_reference_leaves_the_regime_inert_rather_than_guessing() -> None:
    """Preflight is what prevents this pairing; the venue itself must not invent a base price."""
    rule = KrxTradeRule(NAME, Decimal("1"), Decimal("1"), False, price_limit_rate=PRICE_LIMIT_RATE)
    assert rule.permits_side_at(Side.BUY, Decimal("13000"), None) is True
