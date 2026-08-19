from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.fills import ZeroDealtReason
from vqapr.exchange.venue import AcademicExchange, ListingRule, Side
from vqapr.orders.batches import OrderBatch, OrderRequest
from vqapr.valuation.marking import ValuationService

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
            instrument: ListingRule(
                instrument_id=instrument,
                quantity_step=Decimal("0.001"),
                minimum_quantity=Decimal("0.001"),
                fractional_allowed=True,
                permitted_sides=frozenset({Side.BUY, Side.SELL}),
            )
            for instrument in ("A", "B", "C")
        }
    )


def _snapshot(*rows: ExactExecutionRow, missing: tuple[str, ...] = ()) -> ExactExecutionSnapshot:
    return ExactExecutionSnapshot(_AT, rows, (), missing, ())


def test_academic_full_fills_are_fractional_and_deterministic() -> None:
    fills = _venue().execute(
        _orders(_request("B", "-1.25"), _request("A", "2.5")),
        _account(),
        _snapshot(
            ExactExecutionRow(_AT, "B", True, Decimal("20")),
            ExactExecutionRow(_AT, "A", True, Decimal("10")),
        ),
    )

    assert fills.account_version_seen == 7
    assert [(fill.instrument_id, fill.dealt_quantity, fill.price) for fill in fills.fills] == [
        ("A", Decimal("2.5"), Decimal("10")),
        ("B", Decimal("-1.25"), Decimal("20")),
    ]


def test_absent_and_nontradable_orders_are_distinct_typed_zero_dealt_fills() -> None:
    fills = _venue().execute(
        _orders(
            _request("A", "1", execution_price=None),
            _request("B", "1", execution_price=None),
        ),
        _account(),
        _snapshot(ExactExecutionRow(_AT, "B", False, None), missing=("A",)),
    )

    assert [(fill.instrument_id, fill.reason) for fill in fills.fills] == [
        ("A", ZeroDealtReason.ABSENT),
        ("B", ZeroDealtReason.NONTRADABLE),
    ]
    assert all(fill.dealt_quantity == Decimal("0") for fill in fills.fills)


def test_absence_precedes_selected_price_validation_even_for_a_zero_delta_request() -> None:
    fills = _venue().execute(
        _orders(_request("A", "0", execution_price=None)),
        _account(),
        _snapshot(missing=("A",)),
    )

    assert fills.fills[0].requested_quantity == Decimal("0")
    assert fills.fills[0].dealt_quantity == Decimal("0")
    assert fills.fills[0].reason is ZeroDealtReason.ABSENT


def test_invalid_tradable_price_rejects_the_entire_batch() -> None:
    with pytest.raises(ValueError, match="invalid tradable price"):
        _venue().execute(
            _orders(_request("A", "1"), _request("B", "1")),
            _account(),
            _snapshot(
                ExactExecutionRow(_AT, "A", True, Decimal("10")),
                ExactExecutionRow(_AT, "B", True, Decimal("0")),
            ),
        )


def test_duplicate_present_rows_reject_the_entire_batch() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _venue().execute(
            _orders(_request("A", "1")),
            _account(),
            _snapshot(
                ExactExecutionRow(_AT, "A", True, Decimal("10")),
                ExactExecutionRow(_AT, "A", True, Decimal("10")),
            ),
        )


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
