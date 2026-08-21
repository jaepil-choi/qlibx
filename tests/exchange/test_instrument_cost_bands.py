"""A cost band selects an instrument category, and the account pays exactly that band.

The venue this protects is KRX, which charges a securities transaction tax on share sales and
exempts ETFs. Before this existed a band matched on side alone, so every listing on a venue paid
the same rate and an enhanced-index ETF sleeve was charged the share tax it does not owe.

Prices are real KRX closes from ``tests/fixtures/real``; the ETF is declared against one of those
listings so the two categories are compared at an identical price and size.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.domain.enums import Side
from vqapr.domain.instruments import (
    EtfInstrument,
    Instrument,
    InstrumentKind,
    StockInstrument,
    instrument,
    instruments,
)
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.listings import TradeRule
from vqapr.exchange.venue import AcademicExchange
from vqapr.exchange.venues.krx import (
    COMMISSION_RATE,
    SALE_TAX_RATE,
    KrxExchange,
    krx_listing,
    krx_rules,
)
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.budgets import Budget, PortfolioDirection

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real"
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
    return KrxExchange(listings, instruments=instruments)


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

    # A venue-wide declaration cannot express this: both categories pay the share tax.
    flat = KrxExchange([stock, etf]).rules
    assert flat.charge(Side.SELL, notional, etf).tax == notional * SALE_TAX_RATE


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

    fills = venue.execute(batch, account, _snapshot(at, {etf: price}))
    fill = fills.fills[0]
    notional = Decimal("60") * price
    assert fill.cost.tax == Decimal("0")
    assert fill.cost.commission == notional * COMMISSION_RATE

    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.prepare_fill(committed.state, fills, expected_version=3)
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
    stock_fill = stock_venue.execute(
        stock_batch, stock_account, _snapshot(at, {stock: prices[stock]})
    ).fills[0]
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

    exempt = rotate(_two_category_venue(stock, etf).rules)
    venue_wide = rotate(KrxExchange([stock, etf]).rules)

    assert exempt[etf] == venue_wide[etf] == -held, "the whole sleeve is sold either way"
    assert exempt[stock] == Decimal("1213")
    assert venue_wide[stock] == Decimal("1211")
    assert exempt[stock] > venue_wide[stock], (
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
    fills = venue.execute(batch, account, _snapshot(at, {etf: prices[etf], stock: prices[stock]}))
    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.prepare_fill(committed.state, fills, expected_version=0)
    assert prepared.next_snapshot.cash >= 0, "planning must not reserve less than the fill charges"
    assert fills.total_tax == Decimal("0"), "only the exempt sleeve was sold"


def test_a_listed_instrument_has_exactly_one_rate_per_side() -> None:
    """The whole class of "matched 0" and "matched 2" failures is gone by construction.

    Rates used to be a tuple of selectable bands resolved at charge time, guarded against matching
    zero or several. Every part of that existed to support effective-dated rates that nothing ever
    declared -- and the dated path was itself broken until it was measured. A rate is now a field
    on the instrument's own rule, reached by dictionary lookup.
    """
    listings, instruments = krx_rules({"A005930": "stock", "A069500": "etf"})
    venue = KrxExchange(listings, instruments=instruments)
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
    from vqapr.domain.instruments import instruments as build
    from vqapr.exchange.listings import trade_rules_by_kind
    from vqapr.exchange.venues.krx import KRX_TERMS

    listings, _ = krx_rules({"A005930": "stock", "A069500": "etf"})
    assert sorted(listings) == ["A005930", "A069500"]

    mixed = build({"A005930": "stock", "HML": "factor"})
    assert sorted(trade_rules_by_kind(mixed, KRX_TERMS)) == ["A005930"]


def test_a_bare_universe_gets_stock_terms() -> None:
    """Every venue that existed before this keeps charging exactly what it charged."""
    flat = KrxExchange(["A005930"]).rules
    notional = Decimal("1000000")
    assert flat.charge(Side.BUY, notional, "A005930").total == notional * COMMISSION_RATE
    assert flat.charge(Side.SELL, notional, "A005930").total == notional * (
        COMMISSION_RATE + SALE_TAX_RATE
    )
    assert flat.instrument("A005930") is None, "a bare universe declares no category"
    assert flat.kind("A005930") is None
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
    assert free.rules.instruments == {}
