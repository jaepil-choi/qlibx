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
        quantity_targets={},
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
        weight_targets={"B": decimal("0.2")},
        quantity_targets={"A": decimal("1")},
        cash_target=decimal("0.7"),
        budget=_BUDGET,
    )

    assert [(order.instrument_id, order.delta_quantity) for order in batch.requests] == [
        ("Z", decimal("-3")),
        ("A", decimal("0")),
        ("B", decimal("2")),
    ]
    assert [diagnostic.instrument_id for diagnostic in batch.zero_delta_diagnostics] == ["A"]


def test_quantity_target_is_fixed_across_execution_nav_and_price_changes() -> None:
    batch = plan_orders(
        account=snapshot(positions={"A": "2"}),
        execution_time_nav=decimal("100"),
        prices={"A": decimal("10")},
        weight_targets={},
        quantity_targets={"A": decimal("7")},
        cash_target=decimal("0.3"),
        budget=_BUDGET,
    )

    assert batch.requests[0].desired_quantity == decimal("7")
    assert batch.requests[0].delta_quantity == decimal("5")


def test_quantity_target_requires_its_exact_declared_post_trade_cash_fraction() -> None:
    with pytest.raises(ValueError, match="cash_target"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={},
            quantity_targets={"A": decimal("7")},
            cash_target=decimal("0.31"),
            budget=_BUDGET,
        )


def test_complete_desired_positions_enforce_budget_direction_and_bounds() -> None:
    with pytest.raises(ValueError, match="long_only"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={},
            quantity_targets={"A": decimal("-1")},
            cash_target=decimal("1.1"),
            budget=Budget(
                PortfolioDirection.LONG_ONLY,
                decimal("0"),
                decimal("2"),
                decimal("0"),
                decimal("1"),
            ),
        )
    with pytest.raises(ValueError, match="budget bounds"):
        plan_orders(
            account=snapshot(),
            execution_time_nav=decimal("100"),
            prices={"A": decimal("10")},
            weight_targets={},
            quantity_targets={"A": decimal("7")},
            cash_target=decimal("0.3"),
            budget=Budget(
                PortfolioDirection.LONG_ONLY,
                decimal("0"),
                decimal("1"),
                decimal("0"),
                decimal("0.6"),
            ),
        )


def test_missing_price_rejects_a_complete_weight_or_quantity_plan() -> None:
    for weights, quantities, cash in (
        ({"A": decimal("0.25")}, {}, decimal("0.75")),
        ({}, {"A": decimal("3")}, decimal("0.7")),
    ):
        with pytest.raises(ValueError, match="complete desired positions"):
            plan_orders(
                account=snapshot(),
                execution_time_nav=decimal("100"),
                prices={},
                weight_targets=weights,
                quantity_targets=quantities,
                cash_target=cash,
                budget=_BUDGET,
            )


def test_missing_selected_value_for_a_nonzero_holding_fails_before_planning() -> None:
    with pytest.raises(ValueError, match="complete desired positions"):
        plan_orders(
            account=snapshot(positions={"HELD": "1"}),
            execution_time_nav=decimal("100"),
            prices={},
            weight_targets={"TARGET": decimal("0.25")},
            quantity_targets={},
            cash_target=decimal("0.75"),
            budget=_BUDGET,
        )


def test_equal_side_orders_use_instrument_tie_break() -> None:
    batch = plan_orders(
        account=snapshot(positions={"Z": "1", "A": "1"}),
        execution_time_nav=decimal("100"),
        prices={"Z": decimal("1"), "A": decimal("1"), "B": decimal("1")},
        weight_targets={"B": decimal("1")},
        quantity_targets={},
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
