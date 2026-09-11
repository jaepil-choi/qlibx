"""KRX execution profile checked against the committed real market excerpt.

Every price used here is a real KRX close from ``tests/fixtures/real``. The declared cost bands are
3bp brokerage commission on both sides and 20bp sale tax on sells only.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from tests.component.exchange.support import execution_call
from vqapr.component.exchange.krx import COMMISSION_RATE, SALE_TAX_RATE, KrxExchange
from vqapr.data.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.domain.account import Account, AccountMode, AccountSnapshot, AccountState
from vqapr.domain.cost import FillCost
from vqapr.domain.fill import ZeroDealtReason, fill_entries
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.domain.instrument import InstrumentRoster, instrument
from vqapr.domain.intent import Budget, PortfolioDirection
from vqapr.domain.listing import Side
from vqapr.domain.order import plan_orders

FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "real"
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


def _krx(instrument_ids) -> KrxExchange:
    """A KRX venue bound to a roster that calls every id a stock.

    KRX's rate depends on what an instrument IS, so an unbound venue refuses to charge rather than
    assuming a share (issue 013). These tests are about order mechanics -- whole shares, halts,
    rounding, the short refusal -- and each needs a category only because a charge is computed
    along the way. Stating it here is what the Flow does at run assembly, and it makes the
    assumption these tests were already relying on visible.
    """
    ids = list(instrument_ids)
    venue = KrxExchange(ids)
    venue._rules = venue.rules.with_registry(
        InstrumentRoster({name: instrument(name, "stock") for name in ids})
    )
    return venue


def test_declared_cost_bands_match_the_agreed_rates() -> None:
    assert Decimal("0.0003") == COMMISSION_RATE
    assert Decimal("0.002") == SALE_TAX_RATE
    rules = _krx(["A005930"]).rules
    buy = rules.charge(Side.BUY, Decimal("1000000"), "A005930")
    sell = rules.charge(Side.SELL, Decimal("1000000"), "A005930")
    assert buy == FillCost(Decimal("300.0000"), Decimal("0"))
    assert sell == FillCost(Decimal("300.0000"), Decimal("2000.000"))


def test_real_prices_produce_whole_share_orders_that_fit_cash(real_close) -> None:
    at, prices = real_close
    exchange = _krx(sorted(prices))
    account = AccountSnapshot(0, Decimal("1000000000"), {})
    weight = Decimal(1) / Decimal(len(prices))

    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash,
        prices=prices,
        weight_targets=dict.fromkeys(sorted(prices), weight),
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=exchange.rules,
    )

    for request in batch.requests:
        assert request.delta_quantity == request.delta_quantity.to_integral_value()
        assert request.delta_quantity > 0

    fills = exchange.execute(execution_call(exchange, batch, account, _snapshot(at, prices)))
    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.append(committed.state, fill_entries(at, fills), expected_version=0)

    assert prepared.next_snapshot.cash >= 0, "whole-share planning must stay inside real cash"
    assert sum(fill.cost.tax for fill in fills.fills) == 0, "a pure buy programme pays no sale tax"
    for fill in fills.fills:
        expected = abs(fill.dealt_quantity) * fill.price * COMMISSION_RATE
        assert fill.cost.commission == expected
        assert fill.cost.tax == 0


def test_sells_pay_commission_and_sale_tax_on_real_prices(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = _krx([instrument])
    held = Decimal("100")
    account = AccountSnapshot(3, Decimal("5000000"), {instrument: held})

    nav = account.cash + held * price
    batch = plan_orders(
        account=account,
        execution_time_nav=nav,
        prices={instrument: price},
        weight_targets={instrument: Decimal("40") * price / nav},
        cash_target=(account.cash + Decimal("60") * price) / nav,
        budget=LONG_ONLY_SHARES,
        rules=exchange.rules,
    )
    request = batch.requests[0]
    assert request.delta_quantity == Decimal("-60")

    fills = exchange.execute(execution_call(exchange, batch, account, _snapshot(at, {instrument: price})))
    fill = fills.fills[0]
    notional = Decimal("60") * price
    assert fill.cost.commission == notional * COMMISSION_RATE
    assert fill.cost.tax == notional * SALE_TAX_RATE
    assert fill.cash_delta == notional - fill.cost.total

    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.append(committed.state, fill_entries(at, fills), expected_version=3)
    assert prepared.next_snapshot.cash == account.cash + notional - fill.cost.total
    assert prepared.next_snapshot.positions[instrument] == Decimal("40")


def test_krx_refuses_to_open_a_short_position(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = _krx([instrument])
    account = AccountSnapshot(0, Decimal("1000000"), {})

    batch = plan_orders(
        account=account,
        execution_time_nav=Decimal("1000000"),
        prices={instrument: price},
        weight_targets={instrument: Decimal("-10") * price / Decimal("1000000")},
        cash_target=(Decimal("1000000") + Decimal("10") * price) / Decimal("1000000"),
        budget=SIGNED_SHARES,
        rules=exchange.rules,
    )
    with pytest.raises(ValueError, match="does not support short selling"):
        exchange.execute(execution_call(exchange, batch, account, _snapshot(at, {instrument: price})))


def test_halted_real_instrument_is_zero_dealt_and_free(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = _krx([instrument])
    account = AccountSnapshot(0, Decimal("1000000000"), {})

    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash,
        prices={instrument: price},
        weight_targets={instrument: Decimal("1")},
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=exchange.rules,
    )
    fills = exchange.execute(execution_call(exchange, 
        batch, account, _snapshot(at, {instrument: price}, halted=frozenset({instrument}))
    ))
    fill = fills.fills[0]
    assert fill.dealt_quantity == 0
    assert fill.reason is ZeroDealtReason.NONTRADABLE
    assert fill.cost.total == 0
    assert fill.requested_quantity > 0, "the refused size stays visible as requested"


def test_rounding_residual_stays_visible_against_the_intended_position(real_close) -> None:
    at, prices = real_close
    instrument = sorted(prices)[0]
    price = prices[instrument]
    exchange = _krx([instrument])
    account = AccountSnapshot(0, Decimal("1000000000"), {})

    intended = account.cash / price
    batch = plan_orders(
        account=account,
        execution_time_nav=account.cash,
        prices={instrument: price},
        weight_targets={instrument: Decimal("1")},
        cash_target=Decimal("0"),
        budget=LONG_ONLY,
        rules=exchange.rules,
    )
    dealt = batch.requests[0].delta_quantity
    assert dealt < intended, "a whole-share venue can only round toward zero"
    assert intended - dealt < Decimal("1")

    fills = exchange.execute(execution_call(exchange, batch, account, _snapshot(at, {instrument: price})))
    committed = Account(mode=AccountMode.LONG_ONLY)
    committed.bind(AccountState(account))
    prepared = committed.append(committed.state, fill_entries(at, fills), expected_version=0)
    residual_cash = account.cash - dealt * price - fills.fills[0].cost.total
    assert prepared.next_snapshot.cash == residual_cash
