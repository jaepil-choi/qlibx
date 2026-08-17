"""KRX execution profile checked against the committed real market excerpt.

Every price used here is a real KRX close from ``tests/fixtures/real``. The declared cost bands are
3bp brokerage commission on both sides and 20bp sale tax on sells only.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.domain.enums import Side
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.costs import CostRule, FillCost, charge_fill, select_cost_rule
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.fills import ZeroDealtReason
from vqapr.exchange.listings import ExchangeRulesView
from vqapr.exchange.venues.krx import COMMISSION_RATE, SALE_TAX_RATE, KrxExchange
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
SIGNED_SHARES = Budget(
    PortfolioDirection.SIGNED, Decimal("0"), Decimal("10"), Decimal("-100000"), Decimal("100000")
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


def _snapshot(
    at: datetime, prices: dict[str, Decimal], *, halted: frozenset[str] = frozenset()
) -> ExactExecutionSnapshot:
    rows = tuple(
        ExactExecutionRow(at, instrument, instrument not in halted, price)
        for instrument, price in sorted(prices.items())
    )
    return ExactExecutionSnapshot(at, rows, (), (), ())


def test_declared_cost_bands_match_the_agreed_rates() -> None:
    assert Decimal("0.0003") == COMMISSION_RATE
    assert Decimal("0.002") == SALE_TAX_RATE
    rules = KrxExchange(["A005930"]).rules
    buy = rules.charge(Side.BUY, Decimal("1000000"))
    sell = rules.charge(Side.SELL, Decimal("1000000"))
    assert buy == FillCost(Decimal("300.0000"), Decimal("0"))
    assert sell == FillCost(Decimal("300.0000"), Decimal("2000.000"))


def test_exactly_one_cost_rule_must_match_a_side() -> None:
    duplicated = (
        CostRule("a", Side.BUY, Decimal("0.0003"), Decimal("0")),
        CostRule("b", Side.BUY, Decimal("0.0005"), Decimal("0")),
    )
    with pytest.raises(ValueError, match="exactly one CostRule"):
        select_cost_rule(duplicated, Side.BUY)
    with pytest.raises(ValueError, match="exactly one CostRule"):
        charge_fill(duplicated, Side.SELL, Decimal("1"))


def test_cost_bands_may_be_effective_dated_without_changing_flat_venues(real_close) -> None:
    """KRX ships flat rates, but a venue may declare dated bands and stay unambiguous."""
    at, _ = real_close
    switch = LocalInstantDeclaration(at.date(), time(0, 0), VENUE, 0, "+09:00").instant
    listing = KrxExchange(["A005930"]).rules.listing("A005930")
    dated = ExchangeRulesView(
        "krx",
        {"A005930": listing},
        (
            CostRule("sell-old", Side.SELL, COMMISSION_RATE, Decimal("0.0023"), None, switch),
            CostRule("sell-new", Side.SELL, COMMISSION_RATE, SALE_TAX_RATE, switch, None),
        ),
    )

    before = switch - timedelta(days=1)
    assert dated.at(before).charge(Side.SELL, Decimal("1000000"), before).tax == Decimal(
        "2300.0000"
    )
    assert dated.at(at).charge(Side.SELL, Decimal("1000000"), at).tax == Decimal("2000.000")

    with pytest.raises(ValueError, match="exactly one CostRule"):
        dated.charge(Side.SELL, Decimal("1000000"))

    flat = KrxExchange(["A005930"]).rules
    assert flat.at(at) is flat, "a flat venue needs no narrowing"


def test_real_prices_produce_whole_share_orders_that_fit_cash(real_close) -> None:
    at, prices = real_close
    exchange = KrxExchange(sorted(prices))
    account = AccountSnapshot(0, Decimal("1000000000"), {})
    weight = Decimal(1) / Decimal(len(prices))

    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash,
        prices=prices,
        weight_targets=dict.fromkeys(sorted(prices), weight),
        quantity_targets={},
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=exchange.rules,
    )

    for request in batch.requests:
        assert request.delta_quantity == request.delta_quantity.to_integral_value()
        assert request.delta_quantity > 0

    fills = exchange.execute(batch, account, _snapshot(at, prices))
    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.prepare_fill(committed.state, fills, expected_version=0)

    assert prepared.next_snapshot.cash >= 0, "whole-share planning must stay inside real cash"
    assert fills.total_tax == 0, "a pure buy programme pays no sale tax"
    for fill in fills.fills:
        expected = abs(fill.dealt_quantity) * fill.price * COMMISSION_RATE
        assert fill.cost.commission == expected
        assert fill.cost.tax == 0


def test_sells_pay_commission_and_sale_tax_on_real_prices(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = KrxExchange([instrument])
    held = Decimal("100")
    account = AccountSnapshot(3, Decimal("5000000"), {instrument: held})

    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash + held * price,
        prices={instrument: price},
        weight_targets={},
        quantity_targets={instrument: Decimal("40")},
        cash_target=(account.cash + Decimal("60") * price) / (account.cash + held * price),
        budget=LONG_ONLY_SHARES,
        rules=exchange.rules,
    )
    request = batch.requests[0]
    assert request.delta_quantity == Decimal("-60")

    fills = exchange.execute(batch, account, _snapshot(at, {instrument: price}))
    fill = fills.fills[0]
    notional = Decimal("60") * price
    assert fill.cost.commission == notional * COMMISSION_RATE
    assert fill.cost.tax == notional * SALE_TAX_RATE
    assert fill.cash_delta == notional - fill.cost.total

    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.prepare_fill(committed.state, fills, expected_version=3)
    assert prepared.next_snapshot.cash == account.cash + notional - fill.cost.total
    assert prepared.next_snapshot.positions[instrument] == Decimal("40")


def test_krx_refuses_to_open_a_short_position(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = KrxExchange([instrument])
    account = AccountSnapshot(0, Decimal("1000000"), {})

    batch = plan_orders(
        account=account,
        execution_time_nav=Decimal("1000000"),
        prices={instrument: price},
        weight_targets={},
        quantity_targets={instrument: Decimal("-10")},
        cash_target=(Decimal("1000000") + Decimal("10") * price) / Decimal("1000000"),
        budget=SIGNED_SHARES,
        rules=exchange.rules,
    )
    with pytest.raises(ValueError, match="does not support short selling"):
        exchange.execute(batch, account, _snapshot(at, {instrument: price}))


def test_halted_real_instrument_is_zero_dealt_and_free(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = KrxExchange([instrument])
    account = AccountSnapshot(0, Decimal("1000000000"), {})

    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash,
        prices={instrument: price},
        weight_targets={instrument: Decimal("1")},
        quantity_targets={},
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=exchange.rules,
    )
    fills = exchange.execute(
        batch, account, _snapshot(at, {instrument: price}, halted=frozenset({instrument}))
    )
    fill = fills.fills[0]
    assert fill.dealt_quantity == 0
    assert fill.reason is ZeroDealtReason.NONTRADABLE
    assert fill.cost.total == 0
    assert fill.requested_quantity > 0, "the refused size stays visible as requested"


def test_rounding_residual_stays_visible_against_the_intended_position(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = KrxExchange([instrument])
    account = AccountSnapshot(0, Decimal("1000000000"), {})

    intended = account.cash / price
    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash,
        prices={instrument: price},
        weight_targets={instrument: Decimal("1")},
        quantity_targets={},
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=exchange.rules,
    )
    dealt = batch.requests[0].delta_quantity
    assert dealt < intended, "a whole-share venue can only round toward zero"
    assert intended - dealt < Decimal("1")

    fills = exchange.execute(batch, account, _snapshot(at, {instrument: price}))
    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.prepare_fill(committed.state, fills, expected_version=0)
    residual_cash = account.cash - dealt * price - fills.fills[0].cost.total
    assert prepared.next_snapshot.cash == residual_cash
