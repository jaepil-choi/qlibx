"""Design §6.1: a venue is handed the order batch, the market state, the account, and the
instrument dictionary -- and nothing else. The dictionary is a field of `ExecutionCall`, the
venue's rules are bound to it there, and a view bound to another dictionary is refused."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.instruments import InstrumentRoster, instrument
from vqapr.domain.orders import OrderBatch, OrderRequest
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.venue import ExecutionCall
from vqapr.exchange.venues.krx import KrxExchange

AT = datetime(2024, 3, 5, 6, 30, tzinfo=UTC)
STOCK, ETF = "A005930", "A069500"
DICTIONARY = InstrumentRoster({STOCK: instrument(STOCK, "stock"), ETF: instrument(ETF, "etf")})


def _call(venue: KrxExchange, instruments: InstrumentRoster, rules=None) -> ExecutionCall:
    price = Decimal("1000")
    return ExecutionCall(
        at=AT,
        orders=OrderBatch(
            0,
            (
                OrderRequest(STOCK, Decimal("10"), Decimal("0"), Decimal("-10"), price, None),
                OrderRequest(ETF, Decimal("10"), Decimal("0"), Decimal("-10"), price, None),
            ),
        ),
        account=AccountSnapshot(0, Decimal("0"), {STOCK: Decimal("10"), ETF: Decimal("10")}),
        snapshot=ExactExecutionSnapshot(
            AT,
            (ExactExecutionRow(AT, STOCK, True, price), ExactExecutionRow(AT, ETF, True, price)),
            (),
            (),
            (),
        ),
        instruments=instruments,
        rules=venue.rules if rules is None else rules,
    )


def test_the_call_binds_the_venues_rules_to_its_dictionary() -> None:
    venue = KrxExchange([STOCK, ETF])
    assert venue.rules.registry is None, "the venue's own view declares no identity"

    call = _call(venue, DICTIONARY)

    assert call.rules.registry is not None
    assert call.rules.registry.instruments == DICTIONARY.instruments
    assert venue.rules.registry is None, "binding is the call's; the venue stores nothing"
    fills = {fill.instrument_id: fill for fill in venue.execute(call).fills}
    assert fills[STOCK].kind == "stock" and fills[ETF].kind == "etf"
    assert fills[STOCK].cost.tax > 0 and fills[ETF].cost.tax == 0, (
        "what an id IS comes from the dictionary the call carries"
    )


def test_a_view_bound_to_another_dictionary_is_refused() -> None:
    venue = KrxExchange([STOCK, ETF])
    other = InstrumentRoster({STOCK: instrument(STOCK, "etf"), ETF: instrument(ETF, "stock")})

    with pytest.raises(ValueError, match="different instrument dictionary"):
        _call(venue, DICTIONARY, rules=venue.rules.with_registry(other))
    # The same dictionary, already bound, is simply carried.
    call = _call(venue, DICTIONARY, rules=venue.rules.with_registry(DICTIONARY))
    assert call.rules.registry is not None


def test_the_call_takes_a_dictionary_and_nothing_else_for_identity() -> None:
    venue = KrxExchange([STOCK, ETF])
    with pytest.raises(TypeError, match="InstrumentRoster"):
        _call(venue, {STOCK: instrument(STOCK, "stock")})  # type: ignore[arg-type]
    assert {field for field in ExecutionCall.__dataclass_fields__} == {
        "at", "orders", "account", "snapshot", "instruments", "rules"
    }
