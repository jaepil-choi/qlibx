"""Translating a public venue declaration onto the engine's exchange.

The public `Academic` puts quantity step, price step and costs at the venue, because that
is where those economics belong. The engine repeats them per listing. These tests pin the
expansion, and pin the places where a silent guess would decide the caller's economics for
them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr._internal.venue_bridge import engine_access, engine_exchange, side_costs
from vqapr.venues import Academic, Listing, ListingAccess, VenueCost


def _venue(**overrides):
    defaults = {
        "listings": (
            Listing(instrument_id="A005930", access=ListingAccess.SIGNED),
            Listing(instrument_id="A000660", access=ListingAccess.LONG_ONLY),
        ),
        "quantity_step": Decimal("1"),
        "price_step": Decimal("0.1"),
        "costs": (
            VenueCost(side="buy", commission_rate=Decimal("0.0015"), tax_rate=Decimal("0")),
            VenueCost(
                side="sell", commission_rate=Decimal("0.0015"), tax_rate=Decimal("0.0023")
            ),
        ),
    }
    defaults.update(overrides)
    return Academic(**defaults)


def test_a_venue_becomes_an_engine_exchange():
    exchange = engine_exchange(_venue(), exchange_id="krx")
    assert exchange.exchange_id == "krx"
    assert sorted(exchange.listings) == ["A000660", "A005930"]


def test_venue_level_costs_reach_every_listing():
    """One fee schedule on the venue, applied to all of it - not just the first listing."""
    exchange = engine_exchange(_venue())
    for instrument in ("A005930", "A000660"):
        rule = exchange.listings[instrument]
        assert rule.buy.commission_rate == Decimal("0.0015")
        assert rule.sell.tax_rate == Decimal("0.0023")


def test_the_quantity_step_becomes_the_minimum_quantity():
    """The public shape has no separate minimum; one step is the smallest trade."""
    exchange = engine_exchange(_venue(quantity_step=Decimal("5")))
    rule = exchange.listings["A005930"]
    assert rule.quantity_step == Decimal("5")
    assert rule.minimum_quantity == Decimal("5")


def test_each_listing_keeps_its_own_access():
    exchange = engine_exchange(_venue())
    assert exchange.listings["A005930"].access.value == "signed"
    assert exchange.listings["A000660"].access.value == "long_only"


def test_access_translates_by_value_not_by_identity():
    """The two enums are distinct classes that share member values."""
    from vqapr.exchange.listings import ListingAccess as EngineAccess

    assert ListingAccess is not EngineAccess
    for member in ListingAccess:
        translated = engine_access(member)
        assert isinstance(translated, EngineAccess)
        assert translated.value == member.value


def test_an_already_engine_access_passes_through():
    from vqapr.exchange.listings import ListingAccess as EngineAccess

    assert engine_access(EngineAccess.SIGNED) is EngineAccess.SIGNED


def test_a_foreign_access_value_is_refused():
    with pytest.raises(TypeError, match=r"vqapr\.venues\.ListingAccess"):
        engine_access("signed")


# --- refusals that protect the caller's economics ------------------------------------------


def test_a_side_declared_twice_is_refused():
    """Last-wins would silently pick one of two fee schedules."""
    with pytest.raises(ValueError, match="more than one buy cost"):
        side_costs(
            (
                VenueCost(side="buy", commission_rate=Decimal(0), tax_rate=Decimal(0)),
                VenueCost(side="buy", commission_rate=Decimal(1), tax_rate=Decimal(0)),
            )
        )


def test_an_unknown_side_is_refused():
    with pytest.raises(ValueError, match="must be 'buy' or 'sell'"):
        side_costs((VenueCost(side="hold", commission_rate=Decimal(0), tax_rate=Decimal(0)),))


def test_an_undeclared_side_costs_nothing_rather_than_guessing():
    buy, sell = side_costs(
        (VenueCost(side="buy", commission_rate=Decimal("0.002"), tax_rate=Decimal(0)),)
    )
    assert buy.commission_rate == Decimal("0.002")
    assert sell.commission_rate == Decimal(0)
    assert sell.tax_rate == Decimal(0)


def test_the_declaration_itself_refuses_a_repeated_listing():
    """Refused at construction, so the bridge never sees an ambiguous venue."""
    with pytest.raises(ValueError, match="must not repeat an instrument_id"):
        _venue(
            listings=(
                Listing(instrument_id="A005930", access=ListingAccess.SIGNED),
                Listing(instrument_id="A005930", access=ListingAccess.LONG_ONLY),
            )
        )


def test_the_declaration_itself_refuses_an_empty_venue():
    with pytest.raises(ValueError, match="at least one entry"):
        _venue(listings=())


def test_a_non_venue_is_refused():
    with pytest.raises(TypeError, match=r"vqapr\.venues\.Academic"):
        engine_exchange({"listings": ()})


def test_fractional_trading_is_declared_not_assumed():
    """A venue that silently decides whether fractions exist changes measured economics.

    show_004's academic profile drifted from its baseline because the bridge hardcoded
    `fractional_allowed=False`, so an unquantized academic venue was inexpressible on the
    public surface however fine its `quantity_step` was set.
    """
    whole = engine_exchange(_venue())
    assert whole.listings["A005930"].fractional_allowed is False

    fractional = engine_exchange(_venue(fractional_allowed=True))
    assert fractional.listings["A005930"].fractional_allowed is True
    # Every listing on the venue inherits the declaration, not just the first.
    assert fractional.listings["A000660"].fractional_allowed is True


def test_fractional_allowed_defaults_to_whole_units():
    """A share is indivisible; the permissive case must be asked for."""
    assert _venue().fractional_allowed is False


def test_a_non_bool_fractional_declaration_is_refused():
    with pytest.raises(TypeError, match="fractional_allowed must be a bool"):
        _venue(fractional_allowed="yes")
