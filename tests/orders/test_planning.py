from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.valuation.marking import ValuationService


def decimal(value: str) -> Decimal:
    return Decimal(value)


_BUDGET = Budget(
    PortfolioDirection.LONG_ONLY, decimal("0"), decimal("1"), decimal("0"), decimal("1")
)



def snapshot(
    *, version: int = 3, cash: str = "100", positions: dict[str, str] | None = None
) -> AccountSnapshot:
    return AccountSnapshot(
        version=version,
        cash=decimal(cash),
        positions={key: decimal(value) for key, value in (positions or {}).items()},
    )


def test_weight_target_uses_execution_time_nav_after_a_price_gap() -> None:
    batch = plan_orders(
        account=snapshot(positions={"A": "1"}),
        execution_time_nav=decimal("200"),
        prices={"A": decimal("40")},
        weight_targets={"A": decimal("0.5")},
        cash_target=decimal("0.5"),
        budget=_BUDGET,
    )

    assert batch.requests[0].desired_quantity == decimal("2.5")
    assert batch.requests[0].delta_quantity == decimal("1.5")


def test_omitted_holding_is_a_zero_target_and_sells_precede_buys() -> None:
    batch = plan_orders(
        account=snapshot(positions={"Z": "3", "A": "1"}),
        execution_time_nav=decimal("100"),
        prices={"Z": decimal("10"), "A": decimal("10"), "B": decimal("10")},
        weight_targets={"A": decimal("0.1"), "B": decimal("0.2")},
        cash_target=decimal("0.7"),
        budget=_BUDGET,
    )

    assert [(order.instrument_id, order.delta_quantity) for order in batch.requests] == [
        ("Z", decimal("-3")),
        ("A", decimal("0")),
        ("B", decimal("2")),
    ]
    assert [diagnostic.instrument_id for diagnostic in batch.zero_delta_diagnostics] == ["A"]


def test_an_unchanged_weight_target_needs_no_trade_after_a_price_move() -> None:
    """Price drift alone must not manufacture an order.

    The holding is already exactly the target fraction of the moved NAV, so converting the
    weight at execution-time prices lands on the quantity already held.
    """
    batch = plan_orders(
        account=snapshot(cash="0", positions={"A": "10", "B": "10"}),
        execution_time_nav=decimal("400"),
        prices={"A": decimal("30"), "B": decimal("10")},
        weight_targets={"A": decimal("0.75"), "B": decimal("0.25")},
        cash_target=decimal("0"),
        budget=_BUDGET,
    )

    assert [order.delta_quantity for order in batch.requests] == [decimal("0"), decimal("0")]
    assert [diagnostic.instrument_id for diagnostic in batch.zero_delta_diagnostics] == ["A", "B"]


def test_complete_desired_positions_enforce_budget_direction_and_bounds() -> None:
    with pytest.raises(ValueError, match="long_only"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={"A": decimal("-0.1")},
            cash_target=decimal("1.1"),
            budget=Budget(
                PortfolioDirection.LONG_ONLY,
                decimal("0"),
                decimal("2"),
                decimal("-1"),
                decimal("1"),
            ),
        )
    with pytest.raises(ValueError, match="budget bounds"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={"A": decimal("0.7")},
            cash_target=decimal("0.3"),
            budget=Budget(
                PortfolioDirection.LONG_ONLY,
                decimal("0"),
                decimal("1"),
                decimal("0"),
                decimal("0.6"),
            ),
        )


def test_missing_target_only_price_remains_an_unresolved_exchange_request() -> None:
    weight = plan_orders(
        account=snapshot(),
        execution_time_nav=decimal("100"),
        prices={},
        weight_targets={"A": decimal("0.25")},
        cash_target=decimal("0.75"),
        budget=_BUDGET,
    )
    assert weight.requests[0].execution_price is None
    assert weight.requests[0].unresolved_weight_target == decimal("0.25")
    assert weight.requests[0].desired_quantity == decimal("0")


def test_an_unpriceable_holding_is_kept_rather_than_ending_the_batch() -> None:
    """A delisted holding is a market fact, not a data-contract breach.

    Canon 6.1 assigns an absent row to zero-dealt evidence. Refusing here would end a run on the
    first delisting, so the position is carried at its current quantity, asks for no trade, and
    reaches the Exchange as an unresolved request.
    """
    batch = plan_orders(
        account=snapshot(positions={"HELD": "1"}),
        execution_time_nav=decimal("100"),
        prices={},
        weight_targets={"TARGET": decimal("0.25")},
        cash_target=decimal("0.75"),
        budget=_BUDGET,
    )

    held = next(order for order in batch.requests if order.instrument_id == "HELD")
    assert held.execution_price is None
    assert held.current_quantity == decimal("1")
    assert held.desired_quantity == decimal("1")
    assert held.delta_quantity == decimal("0")


def test_an_unpriceable_holding_is_left_out_of_the_priced_book() -> None:
    """The position stays, but nothing pretends to know what it is worth right now."""
    batch = plan_orders(
        account=snapshot(cash="50", positions={"HELD": "1", "A": "2"}),
        execution_time_nav=decimal("100"),
        prices={"A": decimal("25")},
        weight_targets={"A": decimal("0.5")},
        cash_target=decimal("0.5"),
        budget=_BUDGET,
    )

    priced = next(order for order in batch.requests if order.instrument_id == "A")
    assert priced.desired_quantity == decimal("2")
    assert priced.delta_quantity == decimal("0")


def test_equal_side_orders_use_instrument_tie_break() -> None:
    batch = plan_orders(
        account=snapshot(positions={"Z": "1", "A": "1"}),
        execution_time_nav=decimal("100"),
        prices={"Z": decimal("1"), "A": decimal("1"), "B": decimal("1")},
        weight_targets={"B": decimal("1")},
        cash_target=decimal("0"),
        budget=_BUDGET,
    )

    assert [order.instrument_id for order in batch.requests] == ["A", "Z", "B"]


def test_account_transition_validation_does_not_mutate_the_root() -> None:
    account = Account(mode=AccountMode.LONG_ONLY)
    mutable_positions = {"A": decimal("1")}
    copied = AccountSnapshot(3, decimal("100"), mutable_positions)
    mutable_positions["A"] = decimal("9")
    assert copied.positions["A"] == decimal("1")
    with pytest.raises(TypeError):
        copied.positions["A"] = decimal("2")  # type: ignore[index]

    root = AccountState(snapshot(positions={"A": "1"}))
    short = FillBatch((Fill("A", decimal("-2"), decimal("-2"), decimal("10")),), 3)
    with pytest.raises(ValueError, match="short"):
        account.prepare_fill(root, short, expected_version=3)
    unaffordable = FillBatch((Fill("B", decimal("11"), decimal("11"), decimal("10")),), 3)
    with pytest.raises(ValueError, match="cash"):
        account.prepare_fill(root, unaffordable, expected_version=3)
    with pytest.raises(ValueError, match="expected_version"):
        account.prepare_fill(root, short, expected_version=2)
    assert root == AccountState(snapshot(positions={"A": "1"}))


def test_account_prepares_a_complete_fill_and_mark_transition() -> None:
    root = AccountState(snapshot(cash="10"))
    account = Account(mode=AccountMode.SIGNED)
    fills = FillBatch(
        (
            Fill("A", decimal("1"), decimal("1"), decimal("4")),
            Fill("B", decimal("-1"), Decimal(0), None, ZeroDealtReason.ABSENT),
        ),
        3,
    )

    prepared_fill = account.prepare_fill(root, fills, expected_version=3)
    transition = account.prepare_mark(
        prepared_fill,
        ValuationService().mark(prepared_fill.next_snapshot, {"A": decimal("4")}),
        provenance="test",
    )

    assert transition.next_state.snapshot == AccountSnapshot(4, decimal("6"), {"A": decimal("1")})
    assert len(transition.next_state.fill_history) == 2
    assert transition.next_state.latest_mark is not None
    assert root == AccountState(snapshot(cash="10"))


def test_zero_dealt_fills_prepare_an_unchanged_account_snapshot() -> None:
    root = AccountState(snapshot(cash="10", positions={"HELD": "2"}))
    account = Account(mode=AccountMode.LONG_ONLY)
    before = root.snapshot
    fills = FillBatch(
        (
            Fill("TARGET", decimal("3"), Decimal(0), None, ZeroDealtReason.ABSENT),
            Fill("PAUSED", decimal("-1"), Decimal(0), None, ZeroDealtReason.NONTRADABLE),
        ),
        before.version,
    )

    prepared = account.prepare_fill(root, fills, expected_version=before.version)

    assert prepared.next_snapshot.cash == before.cash
    assert prepared.next_snapshot.positions == before.positions
