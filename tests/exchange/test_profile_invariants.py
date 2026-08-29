"""The invariants both execution profiles hold, pinned once against both.

Issue `002` lists five that follow from Architecture 6.1 and are true of any profile. They were
implied by scattered per-profile tests and asserted nowhere as a set, which is what let the two
profiles carry twenty duplicated lines of the contract check between them without anything
noticing.

Point 5 is the one worth writing down before it is needed: ``|dealt| <= |requested|`` is an
INEQUALITY that is currently always an equality. Writing it as an inequality is what makes room for
a partial fill without changing the contract on the day one arrives.

**A partial fill cannot arise on the academic profile**, and that is structural rather than a
policy this file chose. Academic listings are fractional, so a plan sizes exactly to the cash it
has and leaves no rounding residual; cash exhaustion mid-batch is a whole-share artifact. The
equality therefore holds there for a reason, while on a venue profile it holds only until whole
shares and charged costs disagree with the plan's arithmetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.domain.instruments import instrument
from vqapr.domain.roster import InstrumentRoster
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.fills import ZeroDealtReason
from vqapr.exchange.listings import ListingAccess, TradeRule
from vqapr.exchange.venue import AcademicExchange
from vqapr.exchange.venues.krx import KrxExchange, krx_listings
from vqapr.orders.batches import OrderBatch, OrderRequest

_AT = datetime(2026, 8, 22, 6, 30, tzinfo=UTC)
_PRICE = Decimal("70000")
_NAMES = ("A005930", "A069500")


def _academic() -> AcademicExchange:
    return AcademicExchange(
        {
            name: TradeRule(
                name, Decimal("0.000001"), Decimal("0.000001"), True, ListingAccess.SIGNED
            )
            for name in _NAMES
        }
    )


def _krx() -> KrxExchange:
    venue = KrxExchange(krx_listings(_NAMES, price_limits=False))
    venue._rules = venue.rules.with_registry(
        InstrumentRoster({name: instrument(name, "stock") for name in _NAMES})
    )
    return venue


def _profiles() -> tuple[tuple[str, object], ...]:
    return (("academic", _academic()), ("krx", _krx()))


def _orders(*requests: OrderRequest, version: int = 0) -> OrderBatch:
    return OrderBatch(version, requests)


def _request(name: str, delta: str, *, held: str = "0") -> OrderRequest:
    current = Decimal(held)
    change = Decimal(delta)
    return OrderRequest(
        instrument_id=name,
        current_quantity=current,
        desired_quantity=current + change,
        delta_quantity=change,
        execution_price=_PRICE,
    )


def _snapshot(*rows: ExactExecutionRow) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(_AT, rows, (), (), ())


def _held(**positions: str) -> AccountSnapshot:
    return AccountSnapshot(0, Decimal("10000000"), {k: Decimal(v) for k, v in positions.items()})


@pytest.mark.parametrize("profile", [name for name, _ in _profiles()])
def test_one_fill_per_request_in_instrument_order(profile: str) -> None:
    """Invariant 1. Stable order is what makes a run's fill table comparable across runs."""
    venue = dict(_profiles())[profile]
    fills = venue.execute(
        # Deliberately reversed, so a profile that preserved input order would fail.
        _orders(_request(_NAMES[1], "-10", held="100"), _request(_NAMES[0], "-10", held="100")),
        _held(**{_NAMES[0]: "100", _NAMES[1]: "100"}),
        _snapshot(*(ExactExecutionRow(_AT, name, True, _PRICE) for name in _NAMES)),
    )

    assert [fill.instrument_id for fill in fills.fills] == sorted(_NAMES)


@pytest.mark.parametrize("profile", [name for name, _ in _profiles()])
def test_every_zero_dealt_outcome_names_its_own_cause(profile: str) -> None:
    """Invariant 2. Three causes, three typed reasons -- none of them a silent empty fill."""
    venue = dict(_profiles())[profile]
    absent, nontradable = _NAMES

    fills = venue.execute(
        _orders(
            _request(absent, "-10", held="100"),
            _request(nontradable, "-10", held="100"),
        ),
        _held(**{absent: "100", nontradable: "100"}),
        # `absent` has no row at all; `nontradable` has one that says so.
        _snapshot(ExactExecutionRow(_AT, nontradable, False, _PRICE)),
    )
    reasons = {fill.instrument_id: fill.reason for fill in fills.fills}
    assert reasons[absent] is ZeroDealtReason.ABSENT
    assert reasons[nontradable] is ZeroDealtReason.NONTRADABLE

    # `delta == 0` is the third, and it is not an error: the plan asked for nothing.
    quiet = venue.execute(
        _orders(_request(absent, "0", held="100")),
        _held(**{absent: "100"}),
        _snapshot(ExactExecutionRow(_AT, absent, True, _PRICE)),
    )
    assert quiet.fills[0].reason is ZeroDealtReason.NO_TRADE
    assert quiet.fills[0].dealt_quantity == 0


@pytest.mark.parametrize("profile", [name for name, _ in _profiles()])
def test_a_tradable_row_without_a_price_fails_the_batch(profile: str) -> None:
    """Invariant 3. `is_tradable` is a promise about the price beside it."""
    venue = dict(_profiles())[profile]
    name = _NAMES[0]
    for price in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValueError, match="tradable price"):
            venue.execute(
                _orders(_request(name, "-10", held="100")),
                _held(**{name: "100"}),
                _snapshot(ExactExecutionRow(_AT, name, True, price)),
            )


@pytest.mark.parametrize("profile", [name for name, _ in _profiles()])
def test_a_batch_planned_against_another_account_version_is_refused(profile: str) -> None:
    """Invariant 4. A plan is only valid against the book it was planned from."""
    venue = dict(_profiles())[profile]
    name = _NAMES[0]
    with pytest.raises(ValueError, match=r"account_version"):
        venue.execute(
            _orders(_request(name, "-10", held="100"), version=1),
            _held(**{name: "100"}),
            _snapshot(ExactExecutionRow(_AT, name, True, _PRICE)),
        )


@pytest.mark.parametrize("profile", [name for name, _ in _profiles()])
def test_a_fill_shares_its_requests_sign_and_never_exceeds_it(profile: str) -> None:
    """Invariant 5, written as the inequality it is rather than the equality it happens to be.

    `Fill.__post_init__` already refuses a dealt quantity that exceeds its request or flips its
    sign, so the contract admits a partial fill today. No profile produces one: on the academic
    profile none can arise, because fractional listings leave no rounding residual for cash to run
    out against. Asserting `<=` here rather than `==` is what lets a venue profile produce one
    later without this file having to be rewritten to allow it.
    """
    venue = dict(_profiles())[profile]
    buy, sell = _NAMES

    fills = venue.execute(
        _orders(_request(buy, "10"), _request(sell, "-10", held="100")),
        _held(**{sell: "100"}),
        _snapshot(*(ExactExecutionRow(_AT, name, True, _PRICE) for name in _NAMES)),
    )

    for fill in fills.fills:
        assert abs(fill.dealt_quantity) <= abs(fill.requested_quantity)
        if fill.dealt_quantity != 0:
            assert fill.dealt_quantity * fill.requested_quantity > 0, "sign must be shared"

    # And today it is an equality on both, which is the fact a partial fill would change. Stated
    # so the day it changes is visible here rather than silently absorbed by the `<=` above.
    assert all(
        fill.dealt_quantity == fill.requested_quantity for fill in fills.fills
    ), "no profile produces a partial fill yet"
