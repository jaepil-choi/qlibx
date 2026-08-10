from datetime import UTC, datetime

import pytest

from qlibx.account import (
    Account,
    AccountCommitRejected,
    FillBatch,
    Mark,
    MarkBatch,
    StrategyMemoryStore,
    ValuationStatus,
)
from qlibx.execution import Fill, Side
from qlibx.runtime import BacktestClock, Event

EVENT_TIME = datetime(2025, 1, 2, 15, 30, tzinfo=UTC)


def fill(
    fill_id: str,
    side: Side,
    quantity: float,
    *,
    price: float = 100,
    cost: float = 1,
) -> Fill:
    return Fill(
        fill_id=fill_id,
        instrument_id="A",
        side=side,
        requested_quantity=quantity,
        dealt_quantity=quantity,
        price=price,
        trade_value=quantity * price,
        total_cost=cost,
        cost_rule_id="rule",
        schedule_version="v1",
    )


def account() -> Account:
    return Account(
        account_id="account-1",
        base_currency="KRW",
        initial_cash=10_000,
        instrument_ids=frozenset({"A", "B"}),
    )


def test_fill_batch_commit_is_atomic_versioned_and_idempotent() -> None:
    current = account()
    batch = FillBatch(
        account_id="account-1",
        event_id="event-1",
        as_of=EVENT_TIME,
        fills=(fill("F1", Side.BUY, 10),),
    )

    commit = current.commit(batch, expected_version=0)

    assert commit.version == 1
    assert commit.snapshot.cash == 8_999
    assert commit.snapshot.holdings() == {"A": 10}
    assert commit.snapshot.positions[0].average_cost == 100.1
    with pytest.raises(AccountCommitRejected) as duplicate:
        current.commit(batch, expected_version=1)
    assert duplicate.value.code == "DUPLICATE_EVENT"


def test_failed_batch_changes_nothing() -> None:
    current = account()
    before = current.snapshot()
    invalid = FillBatch(
        account_id="account-1",
        event_id="event-invalid",
        as_of=EVENT_TIME,
        fills=(fill("F1", Side.BUY, 1), fill("F2", Side.SELL, 2)),
    )

    with pytest.raises(AccountCommitRejected) as rejected:
        current.commit(invalid, expected_version=0)

    assert rejected.value.code == "SELL_EXCEEDS_POSITION"
    assert current.snapshot() == before
    assert current.feedback(0, 10).entries == ()


def test_mark_batch_values_every_held_instrument_and_advances_feedback() -> None:
    current = account()
    current.commit(
        FillBatch(
            account_id="account-1",
            event_id="buy",
            as_of=EVENT_TIME,
            fills=(fill("F1", Side.BUY, 10),),
        ),
        expected_version=0,
    )
    assert current.snapshot().valuation_status is ValuationStatus.INCOMPLETE

    commit = current.commit(
        MarkBatch(
            account_id="account-1",
            event_id="mark",
            as_of=EVENT_TIME,
            marks=(Mark("A", 110),),
        ),
        expected_version=1,
    )

    assert commit.snapshot.valuation_status is ValuationStatus.COMPLETE
    assert commit.snapshot.nav == 10_099
    assert commit.snapshot.as_of == EVENT_TIME
    assert commit.snapshot.positions[0].marked_at == EVENT_TIME
    assert current.snapshot(
        evaluation_time=datetime(2025, 1, 3, 15, 30, tzinfo=UTC)
    ).valuation_status is ValuationStatus.STALE
    feedback = current.feedback(0, 10)
    assert feedback.account_id == "account-1"
    assert feedback.after_cursor == 0
    assert [entry.event_id for entry in feedback.entries] == ["buy", "mark"]
    assert feedback.entries[0].fills[0].fill_id == "F1"
    assert feedback.entries[0].marks == ()
    assert feedback.entries[1].fills == ()
    assert feedback.entries[1].marks == (Mark("A", 110),)
    assert feedback.next_cursor == 2
    bounded = current.feedback(1, 1)
    assert bounded.after_cursor == 1
    assert bounded.entries == (feedback.entries[1],)
    assert bounded.next_cursor == 2


def test_account_rejects_out_of_order_changes() -> None:
    current = account()
    current.commit(
        FillBatch(
            account_id="account-1",
            event_id="current",
            as_of=EVENT_TIME,
            fills=(fill("F1", Side.BUY, 1),),
        ),
        expected_version=0,
    )
    before = current.checkpoint()

    with pytest.raises(AccountCommitRejected) as rejected:
        current.commit(
            MarkBatch(
                account_id="account-1",
                event_id="past",
                as_of=datetime(2025, 1, 1, 15, 30, tzinfo=UTC),
                marks=(Mark("A", 110),),
            ),
            expected_version=1,
        )

    assert rejected.value.code == "OUT_OF_ORDER_EVENT"
    assert current.checkpoint() == before


def test_memory_store_is_separate_and_cas_guarded() -> None:
    memory = StrategyMemoryStore()
    updated = memory.commit(
        strategy_id="adaptive",
        value={"belief": 0.6},
        feedback_cursor=2,
        expected_version=0,
    )
    assert updated.version == 1
    with pytest.raises(ValueError, match="stale"):
        memory.commit(
            strategy_id="adaptive",
            value={"belief": 0.7},
            feedback_cursor=3,
            expected_version=0,
        )


def test_memory_commit_identity_is_idempotent_and_conflict_safe() -> None:
    memory = StrategyMemoryStore()
    first = memory.commit(
        strategy_id="adaptive",
        value={"belief": 0.6},
        feedback_cursor=2,
        expected_version=0,
        commit_id="memory-event-1",
    )
    replay = memory.commit(
        strategy_id="adaptive",
        value={"belief": 0.6},
        feedback_cursor=2,
        expected_version=0,
        commit_id="memory-event-1",
    )

    assert replay == first
    assert memory.snapshot("adaptive").version == 1
    with pytest.raises(ValueError, match="conflicting content"):
        memory.commit(
            strategy_id="adaptive",
            value={"belief": 0.7},
            feedback_cursor=2,
            expected_version=0,
            commit_id="memory-event-1",
        )


def test_memory_checkpoint_restores_cas_and_feedback_authority() -> None:
    memory = StrategyMemoryStore()
    committed = memory.commit(
        strategy_id="adaptive",
        value={"belief": 0.6},
        feedback_cursor=2,
        expected_version=0,
    )

    restored = StrategyMemoryStore.from_checkpoint(memory.checkpoint())

    assert restored.snapshot("adaptive") == committed
    with pytest.raises(ValueError, match="stale"):
        restored.commit(
            strategy_id="adaptive",
            value={"belief": 0.7},
            feedback_cursor=3,
            expected_version=0,
        )


def test_account_checkpoint_restores_cas_and_idempotency_authority() -> None:
    current = account()
    applied = FillBatch(
        account_id="account-1",
        event_id="event-1",
        as_of=EVENT_TIME,
        fills=(fill("F1", Side.BUY, 10),),
    )
    current.commit(applied, expected_version=0)

    restored = Account.from_checkpoint(current.checkpoint())

    assert restored.snapshot() == current.snapshot()
    assert restored.feedback(0, 10) == current.feedback(0, 10)
    with pytest.raises(AccountCommitRejected) as duplicate:
        restored.commit(applied, expected_version=1)
    assert duplicate.value.code == "DUPLICATE_EVENT"


def test_realized_pnl_survives_close_reopen_feedback_and_checkpoint() -> None:
    current = account()
    current.commit(
        FillBatch(
            account_id="account-1",
            event_id="buy-1",
            as_of=EVENT_TIME,
            fills=(fill("F1", Side.BUY, 10, price=100, cost=0),),
        ),
        expected_version=0,
    )
    closed = current.commit(
        FillBatch(
            account_id="account-1",
            event_id="sell-1",
            as_of=EVENT_TIME,
            fills=(fill("F2", Side.SELL, 10, price=120, cost=2),),
        ),
        expected_version=1,
    )

    assert closed.snapshot.positions == ()
    assert closed.snapshot.realized_pnl == (("A", 198),)
    assert current.feedback(1, 1).entries[0].realized_pnl == (("A", 198),)

    reopened = current.commit(
        FillBatch(
            account_id="account-1",
            event_id="buy-2",
            as_of=EVENT_TIME,
            fills=(fill("F3", Side.BUY, 5, price=110, cost=0),),
        ),
        expected_version=2,
    )
    assert reopened.snapshot.positions[0].realized_pnl == 198
    current.commit(
        FillBatch(
            account_id="account-1",
            event_id="sell-2",
            as_of=EVENT_TIME,
            fills=(fill("F4", Side.SELL, 5, price=130, cost=3),),
        ),
        expected_version=3,
    )

    restored = Account.from_checkpoint(current.checkpoint())

    assert restored.snapshot().positions == ()
    assert restored.snapshot().realized_pnl == (("A", 295),)
    assert restored.feedback(3, 1).entries[0].realized_pnl == (("A", 97),)


def test_positive_dust_is_rejected_without_mutating_account() -> None:
    current = account()
    current.commit(
        FillBatch(
            account_id="account-1",
            event_id="buy",
            as_of=EVENT_TIME,
            fills=(fill("F1", Side.BUY, 1, cost=0),),
        ),
        expected_version=0,
    )
    before = current.checkpoint()

    with pytest.raises(AccountCommitRejected) as rejected:
        current.commit(
            FillBatch(
                account_id="account-1",
                event_id="dust",
                as_of=EVENT_TIME,
                fills=(fill("F2", Side.SELL, 1 - 5e-13, cost=0),),
            ),
            expected_version=1,
        )

    assert rejected.value.code == "POSITION_DUST_UNSUPPORTED"
    assert current.checkpoint() == before


def test_clock_returns_same_timestamp_handlers_in_priority_order() -> None:
    start = datetime(2025, 1, 2, 9, tzinfo=UTC)
    clock = BacktestClock(start)
    called: list[str] = []
    timestamp = datetime(2025, 1, 2, 15, 30, tzinfo=UTC)
    clock.schedule(Event("MONITOR", timestamp, 20), lambda event: called.append(event.name))
    clock.schedule(Event("MARK", timestamp, 10), lambda event: called.append(event.name))

    handlers = clock.advance_to_next()

    assert [handler.event.name for handler in handlers] == ["MARK", "MONITOR"]
    assert called == []
    for handler in handlers:
        handler.callback(handler.event)
    assert called == ["MARK", "MONITOR"]
    assert clock.is_finished()
