"""Two contracts a venue's rule must keep, both found by comparing profiles against each other.

1. **Quantity is two independent checks.** ``minimum_quantity`` and ``quantity_step`` answer
   different questions, and collapsing them into a ``quantize`` round-trip silently drops the
   minimum for a divisible instrument.
2. **A subclass field reaches the fingerprint.** A venue-specific regime -- a price-limit rate, a
   lot-unit convention -- is part of the declaration, so two rules that differ in it must not look
   identical to the workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.listings import ExchangeRulesView, ListingAccess, TradeRule
from vqapr.exchange.venue import AcademicExchange
from vqapr.exchange.venues.krx import KrxExchange, krx_listing
from vqapr.orders.batches import OrderBatch, OrderRequest

FRACTIONAL = TradeRule("A", Decimal("0.01"), Decimal("0.1"), True, ListingAccess.SIGNED)
WHOLE = TradeRule("B", Decimal("1"), Decimal("1"), False, ListingAccess.LONG_ONLY)
LOT = TradeRule("C", Decimal("100"), Decimal("100"), False, ListingAccess.LONG_ONLY)


def test_minimum_quantity_is_checked_even_when_the_instrument_is_divisible() -> None:
    """The bug: ``quantize`` returns a fractional quantity unchanged, so a round-trip check
    against it always matched and the declared floor was never enforced."""
    assert FRACTIONAL.permits_quantity(Decimal("0.5")) is True
    assert FRACTIONAL.permits_quantity(Decimal("0.1")) is True, "exactly the minimum is allowed"
    assert FRACTIONAL.permits_quantity(Decimal("0.05")) is False, "below the declared minimum"

    # The round-trip spelling that hid it: it agrees for a lot instrument and disagrees here.
    assert FRACTIONAL.quantize(Decimal("0.05")) == Decimal("0.05"), "quantize cannot see a minimum"
    assert LOT.quantize(Decimal("50")) == Decimal("0")


def test_step_and_minimum_are_separate_questions() -> None:
    assert WHOLE.permits_quantity(Decimal("10")) is True
    assert WHOLE.permits_quantity(Decimal("10.5")) is False, "not on the unit"
    assert WHOLE.permits_quantity(Decimal("0.5")) is False, "below the minimum"

    assert LOT.permits_quantity(Decimal("200")) is True
    assert LOT.permits_quantity(Decimal("150")) is False, "on the minimum but not on the step"
    assert LOT.permits_quantity(Decimal("50")) is False, "on neither"

    assert WHOLE.permits_quantity(Decimal("-10")) is False, "an absolute size is expected"


def _snapshot(at: datetime, name: str, price: Decimal) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(at, (ExactExecutionRow(at, name, True, price),), (), (), ())


def test_both_profiles_refuse_the_same_undersized_order() -> None:
    """The check is shared, so the two profiles cannot drift apart on it again."""
    at = datetime(2026, 8, 21, 6, 30, tzinfo=UTC)
    price = Decimal("1000")

    academic = AcademicExchange({"A": FRACTIONAL})
    account = AccountSnapshot(0, Decimal("100000"), {})
    undersized = OrderBatch(
        0, (OrderRequest("A", Decimal("0"), Decimal("0.05"), Decimal("0.05"), price, None),)
    )
    with pytest.raises(ValueError, match="quantity violates listing rule"):
        academic.execute(undersized, account, _snapshot(at, "A", price))

    krx = KrxExchange(["A005930"])
    fractional_order = OrderBatch(
        0,
        (OrderRequest("A005930", Decimal("0"), Decimal("10.5"), Decimal("10.5"), price, None),),
    )
    with pytest.raises(ValueError, match="not a whole share"):
        krx.execute(fractional_order, account, _snapshot(at, "A005930", price))


@dataclass(frozen=True, slots=True)
class _RegimeRule(TradeRule):
    """A venue-specific regime, of the shape `KrxTradeRule.price_limit_rate` will have."""

    price_limit_rate: Decimal | None = None


def test_a_subclass_field_reaches_the_declaration_identity() -> None:
    """Otherwise a rate change silently reuses a frozen component."""
    base = TradeRule("A", Decimal("1"), Decimal("1"), False)
    on = _RegimeRule("A", Decimal("1"), Decimal("1"), False, price_limit_rate=Decimal("0.30"))
    other = _RegimeRule("A", Decimal("1"), Decimal("1"), False, price_limit_rate=Decimal("0.10"))
    off = _RegimeRule("A", Decimal("1"), Decimal("1"), False, price_limit_rate=None)

    assert on.declaration_identity != base.declaration_identity, "the type itself is declared"
    assert on.declaration_identity != other.declaration_identity, "a rate change must be visible"
    assert on.declaration_identity != off.declaration_identity, "so must switching it off"
    assert off.declaration_identity != base.declaration_identity, (
        "an explicitly disabled regime is not the same declaration as no regime at all"
    )

    # Collected from the dataclass definition, so a new field cannot forget to extend identity.
    assert on.declaration_identity[-1] == (("price_limit_rate", "0.30"),)
    assert base.declaration_identity[-1] == ()


def test_a_misspelled_regime_field_fails_at_construction() -> None:
    """The reason this is a typed subclass and not a free-form dictionary."""
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _RegimeRule("A", Decimal("1"), Decimal("1"), False, price_limt_rate=Decimal("0.30"))


def test_a_venue_carrying_regime_rules_has_its_own_fingerprint() -> None:
    """The identity has to survive the whole way up to the view the workspace freezes."""
    plain = ExchangeRulesView("krx", {"A005930": krx_listing("A005930")})
    regime = ExchangeRulesView(
        "krx",
        {
            "A005930": _RegimeRule(
                "A005930",
                Decimal("1"),
                Decimal("1"),
                False,
                ListingAccess.LONG_ONLY,
                krx_listing("A005930").buy,
                krx_listing("A005930").sell,
                price_limit_rate=Decimal("0.30"),
            )
        },
    )
    assert plain.declaration_identity != regime.declaration_identity
