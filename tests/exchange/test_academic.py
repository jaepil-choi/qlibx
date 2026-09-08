from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from tests.exchange.support import execution_call
from vqapr.account.marking import ValuationService
from vqapr.domain.account_state import AccountSnapshot
from vqapr.domain.costs import SideCost
from vqapr.domain.fills import ZeroDealtReason
from vqapr.domain.instruments import InstrumentKind, InstrumentRoster, instrument
from vqapr.domain.orders import OrderBatch, OrderRequest
from vqapr.domain.values import Side
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.listings import ExchangeRulesView, ListingAccess, TradeTerms
from vqapr.exchange.venue import AcademicExchange, TradeRule

_AT = datetime(2024, 1, 2, 15, 30, tzinfo=UTC)


def _account(*, positions: dict[str, Decimal] | None = None) -> AccountSnapshot:
    return AccountSnapshot(version=7, cash=Decimal("100"), positions=positions or {})


def _orders(*requests: OrderRequest) -> OrderBatch:
    return OrderBatch(requests=requests, account_version=7)


def _request(
    instrument_id: str, delta: str, *, execution_price: Decimal | None = Decimal("10")
) -> OrderRequest:
    quantity = Decimal(delta)
    return OrderRequest(
        instrument_id=instrument_id,
        current_quantity=Decimal("0"),
        desired_quantity=quantity,
        delta_quantity=quantity,
        execution_price=execution_price,
    )


def _venue() -> AcademicExchange:
    return AcademicExchange(
        {
            instrument: TradeRule(
                instrument_id=instrument,
                quantity_step=Decimal("0.001"),
                minimum_quantity=Decimal("0.001"),
                fractional_allowed=True,
                access=ListingAccess.SIGNED,
            )
            for instrument in ("A", "B", "C")
        }
    )


def _snapshot(*rows: ExactExecutionRow, missing: tuple[str, ...] = ()) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(_AT, rows, (), missing, ())


def test_academic_full_fills_are_fractional_and_deterministic() -> None:
    fills = _venue().execute(execution_call(_venue(), 
        _orders(_request("B", "-1.25"), _request("A", "2.5")),
        _account(),
        _snapshot(
            ExactExecutionRow(_AT, "B", True, Decimal("20")),
            ExactExecutionRow(_AT, "A", True, Decimal("10")),
        ),
    ))

    assert fills.account_version_seen == 7
    assert [(fill.instrument_id, fill.dealt_quantity, fill.price) for fill in fills.fills] == [
        ("A", Decimal("2.5"), Decimal("10")),
        ("B", Decimal("-1.25"), Decimal("20")),
    ]


def test_absent_and_nontradable_orders_are_distinct_typed_zero_dealt_fills() -> None:
    fills = _venue().execute(execution_call(_venue(), 
        _orders(
            _request("A", "1", execution_price=None),
            _request("B", "1", execution_price=None),
        ),
        _account(),
        _snapshot(ExactExecutionRow(_AT, "B", False, None), missing=("A",)),
    ))

    assert [(fill.instrument_id, fill.reason) for fill in fills.fills] == [
        ("A", ZeroDealtReason.ABSENT),
        ("B", ZeroDealtReason.NONTRADABLE),
    ]
    assert all(fill.dealt_quantity == Decimal("0") for fill in fills.fills)


def test_absence_precedes_selected_price_validation_even_for_a_zero_delta_request() -> None:
    fills = _venue().execute(execution_call(_venue(), 
        _orders(_request("A", "0", execution_price=None)),
        _account(),
        _snapshot(missing=("A",)),
    ))

    assert fills.fills[0].requested_quantity == Decimal("0")
    assert fills.fills[0].dealt_quantity == Decimal("0")
    assert fills.fills[0].reason is ZeroDealtReason.ABSENT


def test_invalid_tradable_price_rejects_the_entire_batch() -> None:
    with pytest.raises(ValueError, match="invalid tradable price"):
        _venue().execute(execution_call(_venue(), 
            _orders(_request("A", "1"), _request("B", "1")),
            _account(),
            _snapshot(
                ExactExecutionRow(_AT, "A", True, Decimal("10")),
                ExactExecutionRow(_AT, "B", True, Decimal("0")),
            ),
        ))


def test_duplicate_present_rows_reject_the_entire_batch() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _venue().execute(execution_call(_venue(), 
            _orders(_request("A", "1")),
            _account(),
            _snapshot(
                ExactExecutionRow(_AT, "A", True, Decimal("10")),
                ExactExecutionRow(_AT, "A", True, Decimal("10")),
            ),
        ))


def test_valuation_marks_every_residual_holding_it_has_a_price_for() -> None:
    account = _account(positions={"B": Decimal("-2"), "A": Decimal("3"), "ZERO": Decimal("0")})

    marks = ValuationService().mark(account, {"A": Decimal("4"), "B": Decimal("5")})

    assert [(mark.instrument_id, mark.quantity, mark.value) for mark in marks.marks] == [
        ("A", Decimal("3"), Decimal("12")),
        ("B", Decimal("-2"), Decimal("-10")),
    ]
    assert marks.total_value == Decimal("2")


def test_a_holding_with_no_price_is_left_out_of_nav_rather_than_ending_the_run() -> None:
    """NAV values what can be priced at this instant.

    A holding the venue published no price for contributes nothing to the denominator instead of
    being priced from a stale quote or ending the run. The position is dropped from the valuation,
    never from the book: it keeps its quantity in the AccountSnapshot.
    """
    account = _account(positions={"B": Decimal("-2"), "A": Decimal("3")})

    marks = ValuationService().mark(account, {"A": Decimal("4")})

    assert [mark.instrument_id for mark in marks.marks] == ["A"]
    assert marks.total_value == Decimal("12")
    # The unpriced holding is still held.
    assert account.positions["B"] == Decimal("-2")


BUY_COST = SideCost(Decimal("0.0003"), Decimal("0"))
SELL_COST = SideCost(Decimal("0.0003"), Decimal("0.0020"))


class _CostedAcademic(AcademicExchange):
    """A subclass that declares a cost and changes nothing else.

    The cost now lives on each instrument's own rule rather than in a separate band tuple, so
    "declaring a cost" and "declaring a listing" are one declaration.
    """

    @property
    def rules(self) -> ExchangeRulesView:
        return ExchangeRulesView(
            self.exchange_id,
            {
                name: rule.replace(buy=BUY_COST, sell=SELL_COST)
                for name, rule in self.listings.items()
            },
        )


class _CategoryPricedAcademic(AcademicExchange):
    """A subclass whose rate follows what the instrument IS, declared the supported way.

    The sibling above prices per instrument, which is right for a genuinely per-instrument fee.
    This one prices per CATEGORY, and states it as `terms_by_kind` rather than baking a rate into
    each rule -- so it keeps no copy of a fact the project owns and cannot disagree with the
    roster (issue 013).
    """

    terms_by_kind: ClassVar[dict[InstrumentKind, TradeTerms]] = {
        InstrumentKind.STOCK: TradeTerms(
            Decimal(1), Decimal(1), False, buy=BUY_COST, sell=SELL_COST
        ),
        InstrumentKind.ETF: TradeTerms(Decimal(1), Decimal(1), False, buy=BUY_COST),
    }


def test_a_subclass_prices_by_category_from_the_roster_and_not_from_its_own_copy() -> None:
    """The channel an extension author needs, so the duplication has an alternative.

    `AcademicExchange.rules` promised that "a subclass may declare one", and the only way to do it
    was a rate per `TradeRule`. For a venue whose schedule follows the category that means holding
    a second copy of what the roster declares, which is how a fill comes to record one category
    and be charged as another. Nothing can detect that from outside -- per-instrument rates are
    legitimate when they are not standing in for a category -- so the defence is a reachable
    correct channel, and this is it.
    """
    venue = _CategoryPricedAcademic(_venue().listings)
    notional = Decimal("1000")

    as_declared = venue.rules.with_registry(
        InstrumentRoster({"A": instrument("A", "stock"), "B": instrument("B", "etf")})
    )
    assert as_declared.charge(Side.SELL, notional, "A").tax == notional * SELL_COST.tax_rate
    assert as_declared.charge(Side.SELL, notional, "B").tax == Decimal("0")

    # The same venue under a different roster charges differently, because the venue holds no
    # category of its own to override it with.
    flipped = venue.rules.with_registry(
        InstrumentRoster({"A": instrument("A", "etf"), "B": instrument("B", "stock")})
    )
    assert flipped.charge(Side.SELL, notional, "A").tax == Decimal("0")
    assert flipped.charge(Side.SELL, notional, "B").tax == notional * SELL_COST.tax_rate

    # And the base profile is untouched: no `terms_by_kind`, so it charges its listings and still
    # answers without a roster.
    plain = _venue().rules
    assert plain.registry is None
    assert plain.charge(Side.SELL, notional, "A").total == Decimal("0")


def test_a_declared_cost_band_is_charged_without_replacing_execute() -> None:
    """A profile may add costs, and adding them must not require overriding the matching.

    `load_exchange` refuses a subclass that replaces `execute`, because an unverified matching
    rule carries an unverified realism claim. Charging what `rules` declares is therefore the
    only way a subclass can price a trade at all.
    """
    venue = _CostedAcademic(_venue().listings)

    fills = venue.execute(execution_call(venue, 
        _orders(_request("A", "10"), _request("B", "-10")),
        _account(positions={"B": Decimal("10")}),
        _snapshot(
            ExactExecutionRow(_AT, "A", True, Decimal("100")),
            ExactExecutionRow(_AT, "B", True, Decimal("100")),
        ),
    ))

    charged = {fill.instrument_id: fill.cost for fill in fills.fills}
    # 1000 of notional each way: 3bp to buy, 3bp plus 20bp of tax to sell.
    assert charged["A"].commission == Decimal("0.3000")
    assert charged["A"].tax == Decimal("0")
    assert charged["B"].commission == Decimal("0.3000")
    assert charged["B"].tax == Decimal("2.0000")


def test_an_undeclared_cost_band_still_charges_nothing() -> None:
    fills = _venue().execute(execution_call(_venue(), 
        _orders(_request("A", "10")),
        _account(),
        _snapshot(ExactExecutionRow(_AT, "A", True, Decimal("100"))),
    ))

    assert fills.fills[0].cost.commission == Decimal("0")
    assert fills.fills[0].cost.tax == Decimal("0")
