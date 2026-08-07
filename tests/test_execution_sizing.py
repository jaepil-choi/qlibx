from datetime import date

import pytest

from qlibx.context import StateAccessRecord, StateHolding
from qlibx.domain import Side
from qlibx.execution import (
    SessionSizingInput,
    SessionSizingRequest,
    SizingError,
    SizingPrice,
    SizingTarget,
    size_session_orders,
)


def state(
    *,
    cash: float,
    nav: float,
    holdings: tuple[StateHolding, ...] = (),
) -> StateAccessRecord:
    return StateAccessRecord(
        account_id="account-1",
        version=1,
        feedback_cursor=0,
        cash=cash,
        nav=nav,
        valuation_status="COMPLETE",
        holdings=holdings,
    )


def request(*targets: tuple[str, float]) -> SessionSizingRequest:
    return SessionSizingRequest(
        session_date=date(2025, 1, 2),
        sizing_price_role="execution_price",
        targets=tuple(
            SizingTarget(instrument_id=instrument, weight=weight)
            for instrument, weight in targets
        ),
    )


def test_sizing_orders_sell_first_then_alphabetically() -> None:
    result = size_session_orders(
        request(("B", 0.5), ("C", 0.5)),
        SessionSizingInput(
            account_state=state(
                cash=0,
                nav=1000,
                holdings=(StateHolding(instrument_id="A", quantity=10),),
            ),
            prices=(
                SizingPrice(instrument_id="A", price=100),
                SizingPrice(instrument_id="B", price=50),
                SizingPrice(instrument_id="C", price=100),
            ),
        ),
    )

    assert tuple((item.side, item.instrument_id) for item in result.orders) == (
        (Side.SELL, "A"),
        (Side.BUY, "B"),
        (Side.BUY, "C"),
    )
    assert tuple(item.quantity for item in result.orders) == (10, 10, 5)


@pytest.mark.parametrize("weight", [1 - 5e-13, 1 + 5e-13])
def test_sizing_suppresses_both_sides_of_the_dead_band(weight: float) -> None:
    result = size_session_orders(
        request(("A", weight)),
        SessionSizingInput(
            account_state=state(
                cash=0,
                nav=1,
                holdings=(StateHolding(instrument_id="A", quantity=1),),
            ),
            prices=(SizingPrice(instrument_id="A", price=1),),
        ),
    )

    assert result.orders == ()


def test_sizing_reports_at_most_twenty_missing_session_prices() -> None:
    targets = tuple((f"I{index:02d}", 0.01) for index in range(25))

    with pytest.raises(SizingError) as captured:
        size_session_orders(
            request(*targets),
            SessionSizingInput(account_state=state(cash=100, nav=100), prices=()),
        )

    assert captured.value.code == "EXECUTION_SESSION_PRICE_MISSING"
    assert captured.value.context["instruments"] == [f"I{index:02d}" for index in range(20)]


@pytest.mark.parametrize("cash", [float("nan"), float("inf"), 0.0, -1.0])
def test_sizing_rejects_non_positive_or_non_finite_nav(cash: float) -> None:
    with pytest.raises(SizingError) as captured:
        size_session_orders(
            request(),
            SessionSizingInput(account_state=state(cash=cash, nav=999), prices=()),
        )

    assert captured.value.code == "EXECUTION_SIZING_NAV_INVALID"


def test_sizing_nav_uses_session_prices_instead_of_stale_account_nav() -> None:
    result = size_session_orders(
        request(("B", 1.0)),
        SessionSizingInput(
            account_state=state(
                cash=0,
                nav=1000,
                holdings=(
                    StateHolding(instrument_id="A", quantity=10, mark=100),
                ),
            ),
            prices=(
                SizingPrice(instrument_id="A", price=50),
                SizingPrice(instrument_id="B", price=50),
            ),
        ),
    )

    assert result.sizing_nav == 500
    assert tuple((item.side, item.instrument_id, item.quantity) for item in result.orders) == (
        (Side.SELL, "A", 10),
        (Side.BUY, "B", 10),
    )