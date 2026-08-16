from __future__ import annotations

from decimal import Decimal

import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot
from vqapr.exchange.fills import Fill, FillBatch, ZeroDealtReason
from vqapr.orders.planning import plan_orders


def decimal(value: str) -> Decimal:
    return Decimal(value)


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
        execution_time_nav=decimal("999"),
        prices={"A": decimal("37")},
        weight_targets={},
        quantity_targets={"A": decimal("7")},
    )

    assert batch.requests[0].desired_quantity == decimal("7")
    assert batch.requests[0].delta_quantity == decimal("5")


def test_equal_side_orders_use_instrument_tie_break() -> None:
    batch = plan_orders(
        account=snapshot(positions={"Z": "1", "A": "1"}),
        execution_time_nav=decimal("0"),
        prices={"Z": decimal("1"), "A": decimal("1"), "B": decimal("1")},
        weight_targets={"B": decimal("1")},
        quantity_targets={},
    )

    assert [order.instrument_id for order in batch.requests] == ["A", "Z", "B"]


def test_account_failures_do_not_mutate_and_snapshot_is_detached() -> None:
    account = Account(snapshot(positions={"A": "1"}), mode=AccountMode.LONG_ONLY)
    detached = account.snapshot()
    source = {"A": decimal("1")}
    copied = AccountSnapshot(3, decimal("100"), source)
    source["A"] = decimal("9")
    assert copied.positions["A"] == decimal("1")
    with pytest.raises(TypeError):
        detached.positions["A"] = decimal("2")  # type: ignore[index]

    before = account.snapshot()
    short = FillBatch((Fill("A", decimal("-2"), decimal("-2"), decimal("10")),), 3)
    with pytest.raises(ValueError, match="short"):
        account.prepare_commit(short, expected_version=3)
    unaffordable = FillBatch((Fill("B", decimal("11"), decimal("11"), decimal("10")),), 3)
    with pytest.raises(ValueError, match="cash"):
        account.prepare_commit(unaffordable, expected_version=3)
    with pytest.raises(ValueError, match="expected_version"):
        account.prepare_commit(
            FillBatch((Fill("A", decimal("-1"), decimal("-1"), decimal("10")),), 3),
            expected_version=2,
        )
    assert account.snapshot() == before
    assert account.journal == ()
    assert account.history == (before,)


def test_account_commits_fill_cash_positions_journal_and_history_atomically() -> None:
    account = Account(snapshot(cash="10"), mode=AccountMode.SIGNED)
    fills = FillBatch(
        (
            Fill("A", decimal("1"), decimal("1"), decimal("4")),
            Fill("B", decimal("-1"), Decimal(0), None, ZeroDealtReason.ABSENT),
        ),
        3,
    )

    prepared = account.prepare_commit(fills, expected_version=3)
    assert account.snapshot().version == 3
    committed = account.commit(prepared)

    assert committed == AccountSnapshot(4, decimal("6"), {"A": decimal("1")})
    assert len(account.journal) == 2
    assert account.history == (snapshot(cash="10"), committed)
    with pytest.raises(ValueError, match="no longer current"):
        account.commit(prepared)
