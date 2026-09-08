"""The four categories `UC-ACADEMIC-001` names, and who decides what may be traded.

    Stock                        a common share
    ETF                          an exchange-traded fund
    tracking-only Index          an index level, referenced rather than held
    synthetic-unit-price Factor  a factor held against a synthetic unit price

The load-bearing claim is that **tradability belongs to the venue, not to the category**. Canon
6.2: *"거래 가능 여부를 넣지 않는 이유 -- 상장 규칙이 이미 표현한다"*. So the same instrument gets
different answers on different venues, and a venue says *listed, never fillable* by declaring
``ListingAccess.NONE``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.exchange.support import execution_call
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.instruments import (
    EtfInstrument,
    FactorInstrument,
    IndexInstrument,
    InstrumentKind,
    StockInstrument,
    instrument,
)
from vqapr.domain.values import Side
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.listings import ExchangeRulesView, ListingAccess, TradeRule
from vqapr.exchange.planning import plan_orders
from vqapr.exchange.venue import AcademicExchange
from vqapr.exchange.venues.krx import krx_listing
from vqapr.portfolio.budgets import Budget, PortfolioDirection

BOTH = ListingAccess.SIGNED
NO_SIDE = ListingAccess.NONE
FINE = Decimal("0.000001")
SIGNED = Budget(
    PortfolioDirection.SIGNED, Decimal("-2"), Decimal("2"), Decimal("-2"), Decimal("2")
)


def _fractional(instrument_id: str, access: ListingAccess = BOTH) -> TradeRule:
    return TradeRule(instrument_id, FINE, FINE, True, access)


def _benchmark_venue() -> ExchangeRulesView:
    """A venue that publishes an index it will not fill, beside a stock it will."""
    return ExchangeRulesView(
        "academic",
        {
            "A005930": _fractional("A005930"),
            "KOSPI200": _fractional("KOSPI200", NO_SIDE),
        },
        {"A005930": StockInstrument("A005930"), "KOSPI200": IndexInstrument("KOSPI200")},
    )


def test_the_four_categories_say_what_a_thing_is_and_nothing_about_trading() -> None:
    assert [kind.value for kind in InstrumentKind] == ["stock", "etf", "index", "factor"]
    assert instrument("A", "stock") == StockInstrument("A")
    assert instrument("A", "etf") == EtfInstrument("A")
    assert instrument("A", "index") == IndexInstrument("A")
    assert instrument("A", "factor") == FactorInstrument("A")

    # Canon 6.2: tradability is not duplicated onto the category.
    for category in (StockInstrument, EtfInstrument, IndexInstrument, FactorInstrument):
        assert not hasattr(category("A"), "tradable")


def test_the_same_instrument_is_tradable_on_one_venue_and_not_another() -> None:
    """The reason tradability cannot live on the category: the answer depends on the venue."""
    factor = FactorInstrument("HML")
    academic = ExchangeRulesView("academic", {"HML": _fractional("HML")}, {"HML": factor})
    research = ExchangeRulesView(
        "reference", {"HML": _fractional("HML", NO_SIDE)}, {"HML": factor}
    )

    assert academic.tradable("HML") is True
    assert research.tradable("HML") is False
    assert academic.instrument("HML") == research.instrument("HML"), "one instrument, two venues"


def test_a_venue_publishes_an_index_by_permitting_no_side() -> None:
    """`listed, never fillable` is a venue judgement, expressed where canon says it belongs."""
    view = _benchmark_venue()
    assert view.kind("KOSPI200") is InstrumentKind.INDEX
    assert view.tradable("KOSPI200") is False
    assert view.tradable("A005930") is True
    assert view.listing("KOSPI200").access is ListingAccess.NONE
    assert not view.listing("KOSPI200").permits_position(Decimal("0"), Decimal("1"))
    # The quantity unit still exists -- an unfillable listing is still a listing.
    assert view.listing("KOSPI200").quantity_step == FINE


def test_cost_is_a_field_on_the_rule_not_a_band_to_match() -> None:
    """A merged rule has exactly one answer per side, so matching cannot fail."""
    from vqapr.domain.costs import SideCost

    exempt = _fractional("KODEX", BOTH)
    taxed = TradeRule(
        "A005930",
        FINE,
        FINE,
        True,
        BOTH,
        buy=SideCost(Decimal("0.0003"), Decimal("0")),
        sell=SideCost(Decimal("0.0003"), Decimal("0.002")),
    )
    notional = Decimal("1000000")
    assert taxed.charge(Side.SELL, notional).tax == Decimal("2000.000")
    assert exempt.charge(Side.SELL, notional).tax == Decimal("0")
    assert taxed.charge(Side.BUY, notional).tax == Decimal("0")


def test_a_target_on_an_untradable_listing_is_refused_by_order_planning() -> None:
    """Refused where the instruction is still visible, not as a side error inside the venue."""
    view = _benchmark_venue()
    with pytest.raises(ValueError, match=r"permits no side on 'academic'"):
        plan_orders(
            account=AccountSnapshot(0, Decimal("1000"), {}),
            execution_time_nav=Decimal("1000"),
            prices={"KOSPI200": Decimal("350")},
            weight_targets={"KOSPI200": Decimal("1")},
            cash_target=Decimal("0"),
            budget=SIGNED,
            rules=view,
        )

    # Priced and untouched is fine: the benchmark can be quoted without being traded.
    batch = plan_orders(
        account=AccountSnapshot(0, Decimal("1000"), {}),
        execution_time_nav=Decimal("1000"),
        prices={"KOSPI200": Decimal("350"), "A005930": Decimal("100")},
        weight_targets={"A005930": Decimal("1")},
        cash_target=Decimal("0"),
        budget=SIGNED,
        rules=view,
    )
    assert {r.instrument_id for r in batch.requests} == {"A005930"}


def test_a_factor_fills_fractionally_through_the_ordinary_path() -> None:
    """A factor book is measured by the account, not by a separate return-weighting path."""
    name = "HML"
    listing = _fractional(name)
    fut = FactorInstrument(name)
    venue = _bound(AcademicExchange({name: listing}, "academic"), {name: fut})

    price = Decimal("1.0500")  # a synthetic unit series the user registered
    nav = Decimal("1000000")
    account = AccountSnapshot(0, nav, {})
    batch = plan_orders(
        account=account,
        execution_time_nav=nav,
        prices={name: price},
        weight_targets={name: Decimal("-0.5")},  # signed: a factor may be held short
        cash_target=Decimal("1.5"),
        budget=SIGNED,
        rules=venue.rules,
    )
    quantity = batch.requests[0].delta_quantity
    assert quantity < 0, "a signed venue may short a factor"
    assert quantity != quantity.to_integral_value(), "a factor is not a whole-unit instrument"
    assert quantity == venue.rules.quantity_for(name, Decimal("-0.5") * nav, price)

    at = datetime(2026, 8, 21, 6, 0, tzinfo=UTC)
    snapshot = ExactExecutionSnapshot(
        at, (ExactExecutionRow(at, name, True, price),), (), (), ()
    )
    fill = venue.execute(execution_call(venue, batch, account, snapshot)).fills[0]
    assert fill.dealt_quantity == quantity, "a fractional listing fills in full"
    assert fill.cost.total == Decimal("0"), "the academic venue declares no band"
    assert fill.cash_delta == -(quantity * price)


def test_a_mixed_academic_venue_declares_all_four() -> None:
    """The `UC-ACADEMIC-001` roster: three fillable categories plus a published index."""
    venue = _bound(
        AcademicExchange(
        {
            "A005930": _fractional("A005930"),
            "A069500": _fractional("A069500"),
            "HML": _fractional("HML"),
            "KOSPI200": _fractional("KOSPI200", NO_SIDE),
        },
            "academic",
        ),

        {
            "A005930": StockInstrument("A005930"),
            "A069500": EtfInstrument("A069500"),
            "HML": FactorInstrument("HML"),
            "KOSPI200": IndexInstrument("KOSPI200"),
        },
    )
    rules = venue.rules
    assert sorted(rules.listings) == ["A005930", "A069500", "HML", "KOSPI200"]
    tradable = {name: rules.tradable(name) for name in sorted(rules.listings)}
    assert tradable == {"A005930": True, "A069500": True, "HML": True, "KOSPI200": False}


def test_krx_style_whole_share_and_factor_quantise_differently() -> None:
    """Category and listing are separate axes: the unit is the venue's, the category is not."""
    whole = ExchangeRulesView(
        "krx", {"A005930": krx_listing("A005930")}, {"A005930": StockInstrument("A005930")}
    )
    fine = ExchangeRulesView(
        "academic", {"HML": _fractional("HML")}, {"HML": FactorInstrument("HML")}
    )

    assert whole.quantize("A005930", Decimal("10.7")) == Decimal("10")
    assert fine.quantize("HML", Decimal("10.7")) == Decimal("10.7")


def _bound(venue, roster):
    """A venue whose view carries the project's roster, as the Flow binds it at run assembly.

    Venues no longer accept a roster, so a test does what production does: build the venue, then
    hand its view the identity it borrows. There is deliberately no public way for a venue to
    acquire one itself.
    """
    from vqapr.domain.instruments import InstrumentRoster

    return _WithRoster(venue, venue.rules.with_registry(InstrumentRoster(roster)))


class _WithRoster:
    """Delegates everything to the venue except `rules`, which serves the bound view."""

    def __init__(self, venue, rules):
        self._venue = venue
        self._bound = rules

    @property
    def rules(self):
        return self._bound

    def execute(self, *args, **kwargs):
        return self._venue.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._venue, name)
