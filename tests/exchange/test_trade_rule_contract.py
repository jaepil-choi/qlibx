"""Two contracts a venue's rule must keep, both found by comparing profiles against each other.

1. **Quantity is two independent checks.** ``minimum_quantity`` and ``quantity_step`` answer
   different questions, and collapsing them into a ``quantize`` round-trip silently drops the
   minimum for a divisible instrument.
2. **A subclass field reaches the fingerprint.** A venue-specific regime -- a price-limit rate, a
   lot-unit convention -- is part of the declaration, so two rules that differ in it must not look
   identical to the workspace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.exchange.support import execution_call
from vqapr.data.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.domain.account import AccountSnapshot
from vqapr.domain.listing import ExchangeRulesView, ListingAccess, TradeRule
from vqapr.domain.order import OrderBatch, OrderRequest
from vqapr.exchange.venue import AcademicExchange
from vqapr.exchange.venues.krx import KrxExchange, krx_listing

FRACTIONAL = TradeRule("A", Decimal("0.01"), Decimal("0.1"), True, ListingAccess.SIGNED)
WHOLE = TradeRule("B", Decimal("1"), Decimal("1"), False, ListingAccess.LONG_ONLY)
LOT = TradeRule("C", Decimal("100"), Decimal("100"), False, ListingAccess.LONG_ONLY)


def test_minimum_quantity_is_checked_even_when_the_instrument_is_divisible() -> None:
    """The bug: ``quantize`` returns a fractional quantity unchanged, so a round-trip check
    against it always matched and the declared floor was never enforced."""
    assert FRACTIONAL.permits_quantity(Decimal("0.5")) is True
    assert FRACTIONAL.permits_quantity(Decimal("0.1")) is True, "exactly the minimum is allowed"
    assert FRACTIONAL.permits_quantity(Decimal("0.05")) is False, "below the declared minimum"


def test_quantize_and_permits_quantity_agree_about_the_floor() -> None:
    """The two must answer the same way, or planning emits an order validation refuses.

    ``quantize`` used to return a sub-minimum fractional quantity unchanged. Planning quantizes a
    delta and the venue then validates it, so a divisible listing produced requests it refused
    outright -- ``quantity violates listing rule``, which ends the run. It is not a caller error
    either: a held position sits wherever the last fills left it, so ``desired - held`` is an
    arbitrary real number and falls under the floor whenever a target barely moves.

    Rounding *toward zero* is what both spellings already mean. Below the floor, zero is the
    correctly rounded size, and the grid stays a separate question -- which is what record 039
    established and this extends to the fractional branch.
    """
    for rule, under, at_least in (
        (FRACTIONAL, Decimal("0.05"), Decimal("0.1")),
        (LOT, Decimal("50"), Decimal("100")),
    ):
        assert rule.quantize(under) == Decimal("0"), "below the floor rounds to no order"
        assert rule.quantize(-under) == Decimal("0"), "and the sign does not change that"
        assert rule.quantize(at_least) == at_least, "exactly the floor is a real order"
        assert rule.permits_quantity(abs(rule.quantize(under))) is False or rule.quantize(
            under
        ) == Decimal("0")

    # A fractional listing still keeps everything above its floor exactly as given: its own
    # divisibility is the grid, so nothing is snapped away.
    assert FRACTIONAL.quantize(Decimal("0.123456789")) == Decimal("0.123456789")


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
        academic.execute(execution_call(academic, undersized, account, _snapshot(at, "A", price)))

    krx = KrxExchange(["A005930"])
    fractional_order = OrderBatch(
        0,
        (OrderRequest("A005930", Decimal("0"), Decimal("10.5"), Decimal("10.5"), price, None),),
    )
    # One refusal, in one set of words: the loop that phrases it is `validate_requests`, shared by
    # both profiles, so the KRX profile no longer has its own "not a whole share" spelling.
    with pytest.raises(ValueError, match=r"quantity violates listing rule for 'A005930': 10\.5"):
        krx.execute(execution_call(krx, fractional_order, account, _snapshot(at, "A005930", price)))


class _RegimeRule(TradeRule):
    """A venue-specific regime, of the shape `KrxTradeRule.price_limit_rate` will have.

    A pydantic subclass: the field is declared and nothing else, and the base constructor
    carries it by keyword.
    """

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

    # Collected from the model's declared fields, so a new field cannot forget to extend identity.
    assert on.declaration_identity[-1] == (("price_limit_rate", "0.30"),)
    assert base.declaration_identity[-1] == ()


def test_a_misspelled_regime_field_fails_at_construction() -> None:
    """The reason this is a typed subclass and not a free-form dictionary."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
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
