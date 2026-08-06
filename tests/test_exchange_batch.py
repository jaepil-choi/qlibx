from datetime import datetime, timezone

from qlibx import OutcomeStatus
from qlibx.execution import (
    CostRule,
    EtfInstrument,
    KrxExchange,
    KrxExchangeConfig,
    MarketQuote,
    Order,
    Side,
    StockInstrument,
)

UTC = timezone.utc


def rule(
    rule_id: str,
    product: str,
    side: Side,
    rate: float,
    *,
    start: datetime = datetime(2025, 1, 1, tzinfo=UTC),
    end: datetime | None = None,
    minimum: float = 0,
) -> CostRule:
    return CostRule(
        rule_id=rule_id,
        product_type=product,
        side=side,
        effective_from=start,
        effective_to=end,
        rate=rate,
        minimum_cost=minimum,
    )


def exchange(*rules: CostRule, participation: float | None = None) -> KrxExchange:
    return KrxExchange(
        KrxExchangeConfig(
            schedule_version="krx-test-v1",
            cost_rules=rules,
            participation_rate=participation,
        )
    )


def stock(identifier: str = "005930", lot: int = 1) -> StockInstrument:
    return StockInstrument(
        instrument_id=identifier,
        exchange_id="XKRX",
        currency="KRW",
        lot_size=lot,
    )


def etf(identifier: str = "069500") -> EtfInstrument:
    return EtfInstrument(
        instrument_id=identifier,
        exchange_id="XKRX",
        currency="KRW",
        lot_size=1,
    )


def test_uc_cost_001_exact_product_and_side_rules() -> None:
    venue = exchange(
        rule("stock-sell", "stock", Side.SELL, 0.0015),
        rule("etf-sell-zero", "etf", Side.SELL, 0),
    )
    venue.add_instrument(stock())
    venue.add_instrument(etf())

    outcome = venue.match_batch(
        event_id="cost-products",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=(Order("005930", Side.SELL, 100), Order("069500", Side.SELL, 100)),
        quotes=(MarketQuote("005930", 1000), MarketQuote("069500", 1000)),
        cash=0,
        holdings={"005930": 100, "069500": 100},
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert outcome.result.fills[0].total_cost == 150
    assert outcome.result.fills[1].total_cost == 0
    assert outcome.result.fills[1].cost_rule_id == "etf-sell-zero"


def test_uc_cost_002_effective_dated_rule() -> None:
    venue = exchange(
        rule(
            "stock-buy-2024",
            "stock",
            Side.BUY,
            0.001,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        rule("stock-buy-2025", "stock", Side.BUY, 0.002),
    )
    venue.add_instrument(stock())
    order = (Order("005930", Side.BUY, 10),)
    quote = (MarketQuote("005930", 1000),)

    old = venue.match_batch(
        event_id="old",
        event_time=datetime(2024, 6, 1, tzinfo=UTC),
        orders=order,
        quotes=quote,
        cash=20_000,
        holdings={},
    )
    new = venue.match_batch(
        event_id="new",
        event_time=datetime(2025, 6, 1, tzinfo=UTC),
        orders=order,
        quotes=quote,
        cash=20_000,
        holdings={},
    )
    assert old.result.fills[0].total_cost == 10
    assert new.result.fills[0].total_cost == 20


def test_uc_cost_003_cash_clipping_uses_final_cost_calculator() -> None:
    venue = exchange(rule("stock-buy", "stock", Side.BUY, 0.01))
    venue.add_instrument(stock())

    outcome = venue.match_batch(
        event_id="cash-clip",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=(Order("005930", Side.BUY, 10),),
        quotes=(MarketQuote("005930", 100),),
        cash=1005,
        holdings={},
    )

    fill = outcome.result.fills[0]
    assert fill.dealt_quantity == 9
    assert fill.total_cost == 9
    assert outcome.result.ending_cash == 96
    assert "CASH_LIMIT" in outcome.result.diagnostics[0].reasons


def test_uc_cost_004_missing_etf_rule_does_not_fall_back_to_stock() -> None:
    venue = exchange(rule("stock-buy", "stock", Side.BUY, 0.001))
    venue.add_instrument(etf())
    holdings: dict[str, float] = {}

    outcome = venue.match_batch(
        event_id="missing-etf",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=(Order("069500", Side.BUY, 10),),
        quotes=(MarketQuote("069500", 1000),),
        cash=20_000,
        holdings=holdings,
    )

    assert outcome.status is OutcomeStatus.UNSUPPORTED
    assert outcome.errors[0].error_code == "EXACT_COST_RULE_MISSING"
    assert holdings == {}


def test_last_sell_bypasses_lot_rounding_but_partial_sell_does_not() -> None:
    venue = exchange(rule("stock-sell", "stock", Side.SELL, 0))
    venue.add_instrument(stock(lot=100))
    last = venue.match_batch(
        event_id="last-sell",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=(Order("005930", Side.SELL, 137),),
        quotes=(MarketQuote("005930", 1000),),
        cash=0,
        holdings={"005930": 137},
    )
    partial = venue.match_batch(
        event_id="partial-sell",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=(Order("005930", Side.SELL, 37),),
        quotes=(MarketQuote("005930", 1000),),
        cash=0,
        holdings={"005930": 137},
    )
    assert last.result.fills[0].dealt_quantity == 137
    assert partial.result.fills[0].dealt_quantity == 0
    assert "LOT_ROUNDING" in partial.result.diagnostics[0].reasons


def test_volume_limit_is_reported() -> None:
    venue = exchange(rule("stock-buy", "stock", Side.BUY, 0), participation=0.1)
    venue.add_instrument(stock(lot=10))
    outcome = venue.match_batch(
        event_id="volume",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=(Order("005930", Side.BUY, 1000),),
        quotes=(MarketQuote("005930", 100, available_volume=500),),
        cash=1_000_000,
        holdings={},
    )
    assert outcome.result.fills[0].dealt_quantity == 50
    assert outcome.result.diagnostics[0].reasons == ("VOLUME_LIMIT",)


def test_uc_scale_001_three_thousand_names_keep_stable_batch_order() -> None:
    venue = exchange(rule("stock-buy", "stock", Side.BUY, 0))
    orders = []
    quotes = []
    for index in range(3000):
        identifier = f"S{index:04d}"
        venue.add_instrument(stock(identifier))
        orders.append(Order(identifier, Side.BUY, 1))
        quotes.append(MarketQuote(identifier, 1))

    outcome = venue.match_batch(
        event_id="scale-3000",
        event_time=datetime(2025, 1, 2, tzinfo=UTC),
        orders=tuple(orders),
        quotes=tuple(quotes),
        cash=3000,
        holdings={},
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    assert len(outcome.result.fills) == 3000
    assert [fill.instrument_id for fill in outcome.result.fills] == [
        order.instrument_id for order in orders
    ]
    assert outcome.result.ending_cash == 0
