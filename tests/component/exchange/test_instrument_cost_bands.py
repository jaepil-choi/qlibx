"""A cost band selects an instrument category, and the account pays exactly that band.

The venue this protects is KRX, which charges a securities transaction tax on share sales and
exempts ETFs. Before this existed a band matched on side alone, so every listing on a venue paid
the same rate and an enhanced-index ETF sleeve was charged the share tax it does not owe.

Prices are real KRX closes from ``tests/fixtures/real``; the ETF is declared against one of those
listings so the two categories are compared at an identical price and size.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from tests.component.exchange.support import execution_call
from vqapr.component.exchange.academic import AcademicExchange
from vqapr.component.exchange.krx import (
    COMMISSION_RATE,
    SALE_TAX_RATE,
    KrxExchange,
    krx_listing,
    krx_rules,
)
from vqapr.data.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.domain.account import Account, AccountMode, AccountSnapshot, AccountState
from vqapr.domain.fill import fill_entries
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.domain.instrument import (
    EtfInstrument,
    Instrument,
    InstrumentKind,
    InstrumentRoster,
    StockInstrument,
    instrument,
    instruments,
)
from vqapr.domain.intent import Budget, PortfolioDirection
from vqapr.domain.listing import Side, TradeRule
from vqapr.domain.order import OrderBatch, OrderRequest, plan_orders

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "real"
VENUE = "Asia/Seoul"
LONG_ONLY = Budget(
    PortfolioDirection.LONG_ONLY, Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")
)
LONG_ONLY_SHARES = Budget(
    PortfolioDirection.LONG_ONLY, Decimal("0"), Decimal("1"), Decimal("0"), Decimal("100000")
)


@pytest.fixture(scope="module")
def real_close() -> tuple[datetime, dict[str, Decimal]]:
    """One real session's closes, taken verbatim from the committed excerpt."""
    manifest = json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))
    path = FIXTURE / str(manifest["execution_path"])
    con = duckdb.connect()
    try:
        session = con.execute(
            f"""
            SELECT DISTINCT CAST(trade_at AT TIME ZONE '{VENUE}' AS DATE)
            FROM read_parquet('{path.as_posix()}') ORDER BY 1 LIMIT 1 OFFSET 3
            """
        ).fetchone()[0]
        rows = con.execute(
            f"""
            SELECT instrument, close FROM read_parquet('{path.as_posix()}')
            WHERE CAST(trade_at AT TIME ZONE '{VENUE}' AS DATE) = DATE '{session.isoformat()}'
            ORDER BY instrument
            """
        ).fetchall()
    finally:
        con.close()
    at = LocalInstantDeclaration(session, time(15, 30), VENUE, 0, "+09:00").instant
    return at, {row[0]: row[1] for row in rows}


def _snapshot(at: datetime, prices: dict[str, Decimal]) -> ExactExecutionSnapshot:
    rows = tuple(ExactExecutionRow(at, name, True, price) for name, price in sorted(prices.items()))
    return ExactExecutionSnapshot(at, rows, (), (), ())


def _two_category_venue(stock: str, etf: str) -> KrxExchange:
    listings, instruments = krx_rules({stock: "stock", etf: "etf"})
    # The venue declares terms; the roster declares identity, bound the way the Flow binds it.
    venue = KrxExchange(listings)
    venue._rules = venue.rules.with_registry(InstrumentRoster(instruments))
    return venue


def _venue_under_roster(kinds: dict[str, str]) -> KrxExchange:
    """One venue built from ids alone, bound to whatever the roster says they are.

    The contrast these tests draw used to be "a venue that declares categories" against "a venue
    that does not", because a bare id list charged everything the stock terms. There is no such
    pair any more: a venue names no category, and what varies is the ROSTER. So the same venue is
    built once and bound twice, which is the comparison that now matters.
    """
    venue = KrxExchange(list(kinds))
    venue._rules = venue.rules.with_registry(
        InstrumentRoster({name: instrument(name, kind) for name, kind in kinds.items()})
    )
    return venue


def test_kind_is_a_venue_independent_fact_with_a_declared_extension_path() -> None:
    assert instrument("A005930", "stock") == StockInstrument("A005930")
    assert instrument("A069500", InstrumentKind.ETF).kind is InstrumentKind.ETF
    assert instruments({"A": "stock", "B": "etf"}) == {
        "A": StockInstrument("A"),
        "B": EtfInstrument("B"),
    }

    # No exchange_id: the same instrument lists on many venues under different quantity rules,
    # and stamping a venue here would force it to be declared once per venue.
    assert not hasattr(StockInstrument("A"), "exchange_id")

    with pytest.raises(ValueError, match="unknown instrument kind"):
        instrument("A", "perpetual")
    with pytest.raises(TypeError, match="base category"):
        Instrument("A")


def test_one_unit_is_one_unit_until_a_category_says_otherwise() -> None:
    """The seam a contract multiplier will use, asserted as the identity it is today."""
    share = StockInstrument("A")
    assert share.notional(Decimal("-3"), Decimal("70000")) == Decimal("210000")
    assert share.quantity_for(Decimal("210000"), Decimal("70000")) == Decimal("3")

    value = Decimal("1234567")
    price = Decimal("81300")
    assert share.notional(share.quantity_for(value, price), price) == value


@pytest.mark.uc("UC-COST-004")
def test_an_etf_is_exempt_from_the_share_sale_tax_at_the_same_price(real_close) -> None:
    """The number the enhanced-index sleeve was being charged wrongly."""
    _, prices = real_close
    stock, etf = sorted(prices)[:2]
    price = prices[stock]
    venue = _two_category_venue(stock, etf)
    # Compare at one identical price so only the declared category differs.
    rules = venue.rules
    notional = Decimal("60") * price

    stock_sell = rules.charge(Side.SELL, notional, stock)
    etf_sell = rules.charge(Side.SELL, notional, etf)

    assert stock_sell.tax == notional * SALE_TAX_RATE
    assert etf_sell.tax == Decimal("0"), "KRX exempts ETFs from the securities transaction tax"
    assert stock_sell.commission == etf_sell.commission == notional * COMMISSION_RATE
    assert stock_sell.total - etf_sell.total == notional * SALE_TAX_RATE

    # A venue built from bare ids expresses it identically, because neither venue holds a
    # category: both read the roster. This line used to assert the opposite -- that a venue-wide
    # declaration could not express the exemption and charged the ETF the share tax -- which was
    # true only because `charge` read the rule the venue was constructed with (issue 013).
    from_ids = KrxExchange([stock, etf]).rules.with_registry(
        InstrumentRoster({stock: instrument(stock, "stock"), etf: instrument(etf, "etf")})
    )
    assert from_ids.charge(Side.SELL, notional, etf).tax == Decimal("0")
    assert from_ids.charge(Side.SELL, notional, stock).tax == notional * SALE_TAX_RATE


@pytest.mark.uc("UC-COST-004")
def test_the_exempt_band_reaches_the_account_through_a_real_fill(real_close) -> None:
    """End to end: the cash the account loses is the cash the declared band charges."""
    at, prices = real_close
    stock, etf = sorted(prices)[:2]
    price = prices[etf]
    venue = _two_category_venue(stock, etf)
    held = Decimal("100")
    account = AccountSnapshot(3, Decimal("5000000"), {etf: held})

    nav = account.cash + held * price
    batch = plan_orders(
        account=account,
        execution_time_nav=nav,
        prices={etf: price},
        weight_targets={etf: Decimal("40") * price / nav},
        cash_target=(account.cash + Decimal("60") * price) / nav,
        budget=LONG_ONLY_SHARES,
        rules=venue.rules,
    )
    assert batch.requests[0].delta_quantity == Decimal("-60")

    fills = venue.execute(execution_call(venue, batch, account, _snapshot(at, {etf: price})))
    fill = fills.fills[0]
    notional = Decimal("60") * price
    assert fill.cost.tax == Decimal("0")
    assert fill.cost.commission == notional * COMMISSION_RATE

    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.append(committed.state, fill_entries(at, fills), expected_version=3)
    assert prepared.next_snapshot.cash == account.cash + notional - fill.cost.total

    # The same sale on the share category costs the tax, from the same account and price.
    stock_venue = _two_category_venue(stock, etf)
    stock_account = AccountSnapshot(3, Decimal("5000000"), {stock: held})
    stock_batch = plan_orders(
        account=stock_account,
        execution_time_nav=stock_account.cash + held * prices[stock],
        prices={stock: prices[stock]},
        weight_targets={
            stock: Decimal("40") * prices[stock] / (stock_account.cash + held * prices[stock])
        },
        cash_target=(stock_account.cash + Decimal("60") * prices[stock])
        / (stock_account.cash + held * prices[stock]),
        budget=LONG_ONLY_SHARES,
        rules=stock_venue.rules,
    )
    stock_fill = stock_venue.execute(execution_call(stock_venue, 
        stock_batch, stock_account, _snapshot(at, {stock: prices[stock]})
    )).fills[0]
    assert stock_fill.cost.tax == Decimal("60") * prices[stock] * SALE_TAX_RATE


def test_the_exempt_sleeve_funds_more_of_the_buy_it_pays_for(real_close) -> None:
    """Planning's cash arithmetic must use the same band the fill will use.

    Selling the sleeve funds the buy, so the tax charged on that sale decides how many shares are
    affordable. Priced venue-wide the sleeve pays a tax it does not owe, and the buy is clipped
    against money that was never going to leave the account.
    """
    at, prices = real_close
    etf, stock = "A005380", "A005930"
    held = Decimal("500")
    account = AccountSnapshot(0, Decimal("0"), {etf: held})
    nav = held * prices[etf]

    def rotate(rules) -> dict[str, Decimal]:
        batch = plan_orders(
            account=account,
            execution_time_nav=nav,
            prices={etf: prices[etf], stock: prices[stock]},
            weight_targets={stock: Decimal("1")},
            cash_target=Decimal("0"),
            budget=LONG_ONLY,
            rules=rules,
        )
        return {request.instrument_id: request.delta_quantity for request in batch.requests}

    # The same venue, twice, under two rosters. What the sleeve IS decides what its sale costs,
    # and therefore how much of the buy that sale funds -- and the venue has no say in it.
    exempt = rotate(_venue_under_roster({stock: "stock", etf: "etf"}).rules)
    taxed = rotate(_venue_under_roster({stock: "stock", etf: "stock"}).rules)

    assert exempt[etf] == taxed[etf] == -held, "the whole sleeve is sold either way"
    assert exempt[stock] == Decimal("1213")
    assert taxed[stock] == Decimal("1211")
    assert exempt[stock] > taxed[stock], (
        "an exempt sleeve leaves the tax in the account, and that money buys shares"
    )

    # And the plan is payable: the account never goes negative once the fills are charged.
    venue = _two_category_venue(stock, etf)
    batch = plan_orders(
        account=account,
        execution_time_nav=nav,
        prices={etf: prices[etf], stock: prices[stock]},
        weight_targets={stock: Decimal("1")},
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=venue.rules,
    )
    fills = venue.execute(execution_call(venue, batch, account, _snapshot(at, {etf: prices[etf], stock: prices[stock]})))
    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.append(committed.state, fill_entries(at, fills), expected_version=0)
    assert prepared.next_snapshot.cash >= 0, "planning must not reserve less than the fill charges"
    assert sum(fill.cost.tax for fill in fills.fills) == Decimal("0"), (
        "only the exempt sleeve was sold"
    )


def test_a_listed_instrument_has_exactly_one_rate_per_side() -> None:
    """The whole class of "matched 0" and "matched 2" failures is gone by construction.

    Rates used to be a tuple of selectable bands resolved at charge time, guarded against matching
    zero or several. Every part of that existed to support effective-dated rates that nothing ever
    declared -- and the dated path was itself broken until it was measured. A rate is now a field
    on the instrument's own rule, reached by dictionary lookup.
    """
    listings, instruments = krx_rules({"A005930": "stock", "A069500": "etf"})
    venue = KrxExchange(listings)
    venue._rules = venue.rules.with_registry(InstrumentRoster(instruments))
    notional = Decimal("1000000")

    for name, expected_tax in (("A005930", notional * SALE_TAX_RATE), ("A069500", Decimal("0"))):
        assert venue.rules.charge(Side.SELL, notional, name).tax == expected_tax
        assert venue.rules.charge(Side.BUY, notional, name).tax == Decimal("0")
        assert venue.rules.charge(Side.BUY, notional, name).commission == (
            notional * COMMISSION_RATE
        )

    # An instrument the venue does not list has no rate, and says so rather than charging zero.
    with pytest.raises(ValueError, match="no listing for"):
        venue.rules.charge(Side.SELL, notional, "NOT-LISTED")


def test_a_category_with_no_terms_is_simply_not_listed() -> None:
    """How a venue declines a whole category without naming anything in it."""
    from vqapr.component.exchange.krx import KRX_TERMS
    from vqapr.domain.instrument import instruments as build
    from vqapr.domain.listing import trade_rules_by_kind

    listings, _ = krx_rules({"A005930": "stock", "A069500": "etf"})
    assert sorted(listings) == ["A005930", "A069500"]

    mixed = build({"A005930": "stock", "HML": "factor"})
    assert sorted(trade_rules_by_kind(mixed, KRX_TERMS)) == ["A005930"]


@pytest.mark.uc("UC-COST-004")
def test_a_batch_reports_what_each_category_paid(real_close) -> None:
    """Separating the rates is only half the job: each fill has to be able to show it.

    An enhanced-index fund holds an ETF sleeve to track the index cheaply, and the number that
    justifies the sleeve is what the sleeve cost. The split is read the way the report reads it
    (`report/measure.py`, `trading`): from each fill's own `kind`, `commission` and `tax`, so a
    consumer holding no venue never re-derives a category. A batch-level aggregate used to exist
    beside this and nothing in the product read it; the per-fill columns are the contract.
    """
    at, prices = real_close
    stock, etf = sorted(prices)[:2]
    price = prices[stock]
    venue = _two_category_venue(stock, etf)
    held = Decimal("100")
    account = AccountSnapshot(0, Decimal("0"), {stock: held, etf: held})
    batch = OrderBatch(
        0,
        tuple(
            OrderRequest(name, held, Decimal("40"), Decimal("-60"), price, None)
            for name in (stock, etf)
        ),
    )
    rows = tuple(ExactExecutionRow(at, name, True, price) for name in (stock, etf))
    fills = venue.execute(execution_call(venue, batch, account, ExactExecutionSnapshot(at, rows, (), (), ())))

    by_kind: dict[InstrumentKind | None, tuple[Decimal, Decimal]] = {}
    for fill in fills.fills:
        commission, tax = by_kind.get(fill.kind, (Decimal("0"), Decimal("0")))
        by_kind[fill.kind] = (commission + fill.cost.commission, tax + fill.cost.tax)
    notional = Decimal("60") * price
    assert by_kind[InstrumentKind.STOCK] == (notional * COMMISSION_RATE, notional * SALE_TAX_RATE)
    assert by_kind[InstrumentKind.ETF] == (notional * COMMISSION_RATE, Decimal("0")), (
        "the sleeve owes no share tax"
    )
    assert set(by_kind) == {InstrumentKind.STOCK, InstrumentKind.ETF}, "no unlabelled bucket"

    # Each fill carries the category it was charged as, so evidence survives a roster edit.
    assert {f.instrument_id: f.kind for f in fills.fills} == {
        stock: InstrumentKind.STOCK,
        etf: InstrumentKind.ETF,
    }


def test_a_rosterless_run_is_refused_by_a_categorised_venue_and_served_by_a_flat_one() -> None:
    """The split `stamped_kind`'s docstring promises, now delivered on the charging side too.

    It states the rule: a run with no roster still executes on a venue that charges one flat rate,
    while a venue whose rate depends on the category refuses. Charging was the half that did not
    follow -- KRX went on billing everything the stock terms, so a rosterless run completed and
    collected the share sale tax under `None`, which is the outcome issue 011.3 named and this now
    forecloses.

    `Fill.kind` of `None` is still the honest answer for a venue that never needed a category.
    """
    at = datetime(2026, 8, 22, 6, 30, tzinfo=UTC)
    price = Decimal("70000")
    account = AccountSnapshot(0, Decimal("0"), {"A005930": Decimal("100")})
    batch = OrderBatch(
        0, (OrderRequest("A005930", Decimal("100"), Decimal("40"), Decimal("-60"), price, None),)
    )
    snapshot = ExactExecutionSnapshot(
        at, (ExactExecutionRow(at, "A005930", True, price),), (), (), ()
    )

    # The call always carries a dictionary (design §6.1); a run with no roster carries an empty
    # one, and a categorised venue refuses the first id it has to charge rather than assuming a
    # share.
    with pytest.raises(KeyError, match="no registered instrument describes"):
        venue = KrxExchange(["A005930"])
        venue.execute(execution_call(venue, batch, account, snapshot))

    # A venue whose rate does not vary by category answers unbound, because it never needed to
    # ask. That is the other half of the same rule, and it is why refusing above is a statement
    # about KRX rather than a new precondition on every venue.
    free = AcademicExchange(
        {"A005930": TradeRule("A005930", Decimal("1"), Decimal("1"), False)}
    ).rules
    assert free.registry is None
    assert free.charge(Side.SELL, Decimal("1000000"), "A005930").total == Decimal("0")


def test_an_unbound_krx_venue_refuses_to_charge_rather_than_assuming_a_share() -> None:
    """The other half of the bypass issue 007 named, now also gone.

    It gave every name stock terms AND recorded no category, so an ETF quietly paid a tax KRX
    exempts. The identity claim was refused first; this pins the charge, which went on answering
    from the rule the venue was constructed with while `stamped_kind` answered from the roster --
    so a fill could say one category and be charged as another (issue 013).

    A KRX rate depends on what the instrument IS, and for an instrument nobody described there is
    no honest answer. Charging one anyway is the silent default this design exists to remove, so
    an unbound venue refuses on BOTH questions rather than on one of them.
    """
    flat = KrxExchange(["A005930"]).rules
    notional = Decimal("1000000")
    for side in (Side.BUY, Side.SELL):
        with pytest.raises(ValueError, match="no instrument roster reached"):
            flat.charge(side, notional, "A005930")
    with pytest.raises(ValueError, match="no instrument roster reached"):
        flat.kind("A005930")

    # Bound, it charges what the ROSTER says -- and the venue named no category to disagree with.
    bound = flat.with_registry(InstrumentRoster({"A005930": instrument("A005930", "stock")}))
    assert bound.charge(Side.BUY, notional, "A005930").total == notional * COMMISSION_RATE
    assert bound.charge(Side.SELL, notional, "A005930").total == notional * (
        COMMISSION_RATE + SALE_TAX_RATE
    )
    exempt = flat.with_registry(InstrumentRoster({"A005930": instrument("A005930", "etf")}))
    assert exempt.charge(Side.SELL, notional, "A005930").tax == Decimal("0"), (
        "the same venue, the same id, a different roster: the category is the project's answer"
    )
    # Sizing still works unbound, because no shipped category overrides the base conversion, so
    # the declared answer and this one are the same number. `_sizing_is_uniform` retires that the
    # moment a category with its own contract size arrives.
    assert flat.notional("A005930", Decimal("-3"), Decimal("100")) == Decimal("300")

    # A cost travels with the rule now, so a venue reusing KRX's rule inherits KRX's rates --
    # the cost is a property of what the venue will do, not of which profile class holds it.
    reused = AcademicExchange({"A005930": krx_listing("A005930")})
    assert reused.rules.charge(Side.SELL, notional, "A005930").tax == notional * SALE_TAX_RATE

    # A rule that declares no cost charges nothing, which is the academic default.
    free = AcademicExchange(
        {"A005930": TradeRule("A005930", Decimal("1"), Decimal("1"), False)}
    )
    assert free.rules.charge(Side.SELL, notional, "A005930").total == Decimal("0")
    # A venue holds no roster at all now: identity is the project's, handed in at assembly.
    assert free.rules.registry is None
