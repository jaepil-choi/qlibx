"""Turn a public `venues.Academic` declaration into the engine's exchange.

The two shapes disagree about where trading granularity and costs live. The public
`Academic` hoists `quantity_step`, `price_step` and `costs` to the venue, because a venue
is where those economics actually belong: one tick size, one fee schedule, applied to
every listing on it. The engine's `TradeRule` repeats them per instrument.

Translating one venue-level fact onto every listing is therefore expansion, not
invention - and it is one-directional. Going the other way would have to reconcile
per-instrument steps that disagree, which is exactly the ambiguity the public shape
removes, so this module does not attempt it.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from vqapr.exchange.venue import AcademicExchange as _EngineExchange

__all__ = (
    "AdaptedExchange",
    "engine_access",
    "engine_exchange",
    "exchange_component_ref",
    "side_costs",
)


def exchange_component_ref(academic: Any, *, component_id: str) -> Any:
    """Register the engine's own `AcademicExchange` configured by a public venue.

    The engine reaches an exchange through a `ComponentRef`: a source file, an object
    name and a config it reconstructs from. A public `venues.Academic` is a value, not a
    class, so it has no source file of its own - which is why `show_003` generates an
    exchange module on disk just to have something to point at.

    Pointing at `AcademicExchange` itself and carrying the venue's listings and costs as
    config avoids writing throwaway source for a declaration the caller already made. The
    fingerprint then covers the shipped exchange's bytes plus that config, so changing
    either changes identity, which is the property the contract actually needs.
    """
    from vqapr._internal.extensions.component import ComponentKind, ComponentRef
    from vqapr._internal.extensions.fingerprint import fingerprint_component
    from vqapr.venues import Academic

    if not isinstance(academic, Academic):
        raise TypeError("academic must be a vqapr.venues.Academic")

    exchange = engine_exchange(academic, exchange_id=component_id)
    config = {
        "listings": {
            instrument: {
                "quantity_step": str(rule.quantity_step),
                "minimum_quantity": str(rule.minimum_quantity),
                "fractional_allowed": rule.fractional_allowed,
                "access": str(rule.access.value),
                "buy_commission": str(rule.buy.commission_rate),
                "buy_tax": str(rule.buy.tax_rate),
                "sell_commission": str(rule.sell.commission_rate),
                "sell_tax": str(rule.sell.tax_rate),
            }
            for instrument, rule in sorted(exchange.listings.items())
        },
        "exchange_id": component_id,
    }
    source = _source_path(AdaptedExchange)
    # Same function the loader re-verifies with, so a registered digest is one the loader
    # will accept rather than reject as drift.
    fingerprint = fingerprint_component(
        source,
        kind=ComponentKind.EXCHANGE,
        object_name=AdaptedExchange.__qualname__,
        config=config,
    )
    return ComponentRef.of(
        component_id,
        ComponentKind.EXCHANGE,
        source,
        AdaptedExchange.__qualname__,
        config=config,
        fingerprint=fingerprint,
    )


def _package_version() -> str:
    from vqapr._internal.extensions.identity import installed_package_version

    return installed_package_version()


def _source_path(cls: type):
    import inspect
    from pathlib import Path

    source = inspect.getsourcefile(cls)
    if not source:
        raise ValueError(f"{cls.__qualname__} has no readable source file")
    return Path(source)


def engine_access(access: Any) -> Any:
    """Translate the public `ListingAccess` onto the engine's own enum.

    They are distinct classes that happen to share member values, so the translation goes
    by value. Matching on name would pass today and break silently the moment either side
    renames a member without changing what it means.
    """
    from vqapr.exchange.listings import ListingAccess as EngineAccess
    from vqapr.venues import ListingAccess as PublicAccess

    if isinstance(access, EngineAccess):
        return access
    if not isinstance(access, PublicAccess):
        raise TypeError("access must be a vqapr.venues.ListingAccess")
    try:
        return EngineAccess(access.value)
    except ValueError as error:
        raise ValueError(
            f"the engine has no listing access matching {access.value!r}"
        ) from error


def side_costs(costs: tuple[Any, ...]) -> tuple[Any, Any]:
    """Split venue-level costs into the engine's buy/sell pair.

    A side declared twice is refused rather than last-wins: two fee schedules for one
    side is an unresolvable declaration, and silently picking one would decide the
    caller's economics for them.
    """
    from vqapr.exchange.costs import SideCost

    seen: dict[str, Any] = {}
    for cost in costs:
        side = str(cost.side).lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"venue cost side must be 'buy' or 'sell'; got {cost.side!r}")
        if side in seen:
            raise ValueError(f"venue declares more than one {side} cost")
        seen[side] = SideCost(
            commission_rate=Decimal(cost.commission_rate),
            tax_rate=Decimal(cost.tax_rate),
        )
    zero = SideCost(commission_rate=Decimal(0), tax_rate=Decimal(0))
    return seen.get("buy", zero), seen.get("sell", zero)


def engine_exchange(academic: Any, *, exchange_id: str = "academic") -> Any:
    """Build the engine's `AcademicExchange` from a public `venues.Academic`.

    Every listing inherits the venue's quantity step and cost schedule. `minimum_quantity`
    takes the quantity step: the public shape has no separate minimum, and the smallest
    tradable amount on a stepped venue is one step.
    """
    from vqapr.venues import Academic

    if not isinstance(academic, Academic):
        raise TypeError("academic must be a vqapr.venues.Academic")
    from vqapr.public import AcademicExchange, TradeRule

    buy, sell = side_costs(academic.costs)
    quantity_step = Decimal(academic.quantity_step)

    rules: dict[str, Any] = {}
    # `Academic` already refuses an empty or duplicated listing set, so this loop does not
    # re-check what the declaration guarantees.
    for listing in academic.listings:
        rules[listing.instrument_id] = TradeRule(
            listing.instrument_id,
            quantity_step,
            quantity_step,
            academic.fractional_allowed,
            engine_access(listing.access),
            buy,
            sell,
        )
    return AcademicExchange(rules, exchange_id)


class AdaptedExchange(_EngineExchange):
    """The one registrable exchange component: a public venue in engine clothing.

    `AcademicExchange` takes a `Mapping[str, TradeRule]`, and a `TradeRule` is not a
    JSON-serialisable value, so the shipped class cannot be reconstructed from a component
    config. This subclass is resolved by the loader from this module by name and rebuilds
    those rules from a flat config - the same shape that made `AdaptedStrategy` work.
    """

    def __init__(self, *, listings: Mapping[str, Mapping[str, object]], exchange_id: str):
        from decimal import Decimal

        from vqapr.exchange.costs import SideCost
        from vqapr.exchange.listings import ListingAccess as EngineAccess
        from vqapr.public import TradeRule

        rules = {
            instrument: TradeRule(
                instrument,
                Decimal(str(spec["quantity_step"])),
                Decimal(str(spec["minimum_quantity"])),
                bool(spec["fractional_allowed"]),
                EngineAccess(str(spec["access"])),
                SideCost(
                    commission_rate=Decimal(str(spec["buy_commission"])),
                    tax_rate=Decimal(str(spec["buy_tax"])),
                ),
                SideCost(
                    commission_rate=Decimal(str(spec["sell_commission"])),
                    tax_rate=Decimal(str(spec["sell_tax"])),
                ),
            )
            for instrument, spec in sorted(listings.items())
        }
        super().__init__(rules, exchange_id)
