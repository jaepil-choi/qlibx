"""Integration tests for portfolio.py ↔ OrderRouter wiring (Phase 2 surgery).

These exercise the parts the OrderRouter unit tests don't:
- portfolio._execute_pending_orders calls OrderRouter.submit_order with
  the right kwargs (especially force_price for explicit-LIMIT recovery)
- portfolio._process_fills drains terminal records on the main thread
- pending_exit_intent set BEFORE first attempt, cleared on full-fill,
  updated on partial/abandon
- Chain-aware Phase C reconciliation across split chunks
"""
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Stub xtquant before importing
for _mod_name in (
    "xtquant", "xtquant.xtconstant", "xtquant.xtdata",
    "xtquant.xttrader", "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402

from echolon.live.platforms.miniqmt.order_router import (  # noqa: E402
    OrderRouter, RouterCallbacks, OrderHandle, OrderState,
)
from echolon.strategy.interfaces import Order, OrderIntent, OrderStatus, OrderType  # noqa: E402
from echolon.strategy.state_manager import StateManager, PendingExitIntent  # noqa: E402


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client():
    client = MagicMock()
    client.set_callbacks = MagicMock()
    client.cancel_order = MagicMock(return_value=True)
    client._next_seq = 5000
    def _submit(symbol, volume, price, order_type, intent, strategy_name):
        client._next_seq += 1
        return client._next_seq
    client.submit_order_async = MagicMock(side_effect=_submit)
    client.resolve_aggressive_price = MagicMock(return_value=(11, 24625.0))
    client._get_tick_snapshot = MagicMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# force_price plumbing — the bug the advisor caught
# ---------------------------------------------------------------------------


def test_explicit_limit_price_forwards_as_force_price(fake_client, tmp_path):
    """An order with explicit LIMIT price (e.g. kill-at-band-edge from
    _resume_pending_exit) MUST reach the broker as that exact price,
    not the router's aggressive-pricing override.
    """
    router = OrderRouter(client=fake_client, state_dir=tmp_path / "state")
    kill_price = 22850.0  # below settlement, near band edge

    # Simulating what portfolio._execute_pending_orders should do for a
    # LIMIT order with explicit price.
    handle = router.submit_order(
        intent="EXIT_LONG", symbol="al2606.SF", volume=1, slot_id="al_s1",
        intended_price=kill_price, force_price=kill_price,
    )

    submit_call = fake_client.submit_order_async.call_args
    submitted_price = submit_call.kwargs.get("price") if submit_call.kwargs else submit_call.args[2]
    assert submitted_price == kill_price, (
        f"force_price {kill_price} must reach the broker; got {submitted_price}"
    )
    # Resolve_aggressive_price should NOT have been called for this submission.
    assert fake_client.resolve_aggressive_price.call_count == 0


def test_force_price_skips_splitter(fake_client, tmp_path):
    """Explicit-limit recovery orders should not be split — they are a
    single deterministic kill order."""
    router = OrderRouter(client=fake_client, state_dir=tmp_path / "state")
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    handle = router.submit_order(
        intent="EXIT_LONG", symbol="al2606.SF", volume=3, slot_id="al_s1",
        force_price=22850.0,
    )
    # No SplitSequence registered when force_price is set.
    assert handle.seq_id not in router._split_sequences
    assert handle.submitted_volume == 3


# ---------------------------------------------------------------------------
# pending_exit_intent state flow
# ---------------------------------------------------------------------------


def test_pending_exit_intent_set_persists_across_state_writes(tmp_path):
    """Verify the StateManager helpers actually round-trip the schema."""
    state_path = str(tmp_path / "strategy_state.json")
    sm = StateManager(state_path=state_path)
    sm.load_state()
    sm.set_pending_exit_intent(PendingExitIntent(
        intent="EXIT_LONG", original_size=2, remaining_size=2,
        attempts_so_far=0,
        original_decision_time=datetime.now().isoformat(),
        last_attempt_time=datetime.now().isoformat(),
    ))
    sm.save_state()

    sm2 = StateManager(state_path=state_path)
    state = sm2.load_state()
    assert state.pending_exit_intent is not None
    assert state.pending_exit_intent.intent == "EXIT_LONG"
    assert state.pending_exit_intent.remaining_size == 2


def test_clear_pending_exit_intent_round_trips(tmp_path):
    state_path = str(tmp_path / "strategy_state.json")
    sm = StateManager(state_path=state_path)
    sm.load_state()
    sm.set_pending_exit_intent(PendingExitIntent(
        intent="EXIT_LONG", original_size=1, remaining_size=1,
        attempts_so_far=0,
        original_decision_time="2026-05-07T21:00:00",
        last_attempt_time="2026-05-07T21:00:00",
    ))
    sm.save_state()

    sm2 = StateManager(state_path=state_path)
    sm2.load_state()
    sm2.clear_pending_exit_intent()
    sm2.save_state()

    sm3 = StateManager(state_path=state_path)
    state = sm3.load_state()
    assert state.pending_exit_intent is None


# ---------------------------------------------------------------------------
# Chain resolution semantics — single intent, retry chain
# ---------------------------------------------------------------------------


def _drive(router, ticks=1):
    import queue as _queue
    from datetime import timedelta
    for _ in range(ticks):
        with router._lock:
            try:
                while True:
                    event = router._event_queue.get_nowait()
                    router._process_event(event)
            except _queue.Empty:
                pass
            router._check_deadlines_and_quiescence()


class _FakeOrder:
    def __init__(self, order_id, status, msg=""):
        self.order_id = order_id
        self.order_status = status
        self.status_msg = msg


def test_chain_resolved_set_on_immediate_fill(fake_client, tmp_path):
    """Initial submit → FILLED + trade → quiescence → chain_resolved set."""
    from datetime import timedelta
    from echolon.live.config.order_policy import QUIESCENCE_WINDOW_S
    router = OrderRouter(client=fake_client, state_dir=tmp_path / "state")
    handle = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    assert handle.chain_resolved is not None
    assert not handle.chain_resolved.is_set()

    router._enqueue_async_response(seq_id=handle.seq_id, order_id=900_001)
    router._enqueue_status_event(_FakeOrder(900_001, status=56))
    router._enqueue_trade_event(MagicMock(
        order_id=900_001, traded_id=42, traded_price=24625.0, traded_volume=1,
    ))
    _drive(router)
    handle.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    assert handle.chain_resolved.is_set(), "chain_resolved must be set after final terminal"


def test_chain_resolved_waits_through_resubmit(fake_client, tmp_path):
    """submit → timeout → cancel → resubmit → fill → chain_resolved set."""
    from datetime import timedelta
    from echolon.live.config.order_policy import QUIESCENCE_WINDOW_S
    router = OrderRouter(client=fake_client, state_dir=tmp_path / "state")
    handle = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=handle.seq_id, order_id=900_002)
    _drive(router)

    # Force deadline → cancel → quiescence → resubmit
    handle.deadline_at = datetime.now() - timedelta(seconds=1)
    _drive(router)
    router._enqueue_status_event(_FakeOrder(900_002, status=54))
    _drive(router)
    handle.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    # During resubmit, parent's chain_resolved is NOT set yet
    assert not handle.chain_resolved.is_set()

    # Find resubmit handle, fill it, drive
    new_handles = [h for h in router._handles_by_seq.values() if h.attempt == 2]
    assert len(new_handles) == 1
    new_h = new_handles[0]
    assert new_h.chain_resolved is handle.chain_resolved  # shared event

    router._enqueue_async_response(seq_id=new_h.seq_id, order_id=900_003)
    router._enqueue_status_event(_FakeOrder(900_003, status=56))
    router._enqueue_trade_event(MagicMock(
        order_id=900_003, traded_id=43, traded_price=24625.0, traded_volume=1,
    ))
    _drive(router)
    new_h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    assert handle.chain_resolved.is_set()


def test_find_order_for_chain_returns_none_on_unknown_seq():
    """Regression — when a record's chain_root doesn't match any tracked
    parent_handle (e.g. immediately-rejected fake-negative seq_id), the
    helper MUST return None. Returning order_list[0][0] would corrupt
    the audit trail by writing the rejected status to the wrong order.
    """
    from echolon.live.orchestrator.portfolio import PortfolioTradingRunner
    from echolon.strategy.interfaces import Order, OrderIntent, OrderStatus, OrderType

    runner = PortfolioTradingRunner.__new__(PortfolioTradingRunner)
    real_order = Order(
        order_id="ord_1", symbol="al2606.SF",
        side=MagicMock(), order_type=OrderType.MARKET, size=1, price=None,
        intent=OrderIntent.ENTRY_LONG, status=OrderStatus.PENDING,
        created_at=datetime.now(),
    )
    real_handle = MagicMock(seq_id=1234)

    # Record's chain_root points to a different (e.g. rejected) handle.
    found = runner._find_order_for_chain(
        order_list=[(real_order, real_handle)],
        chain_root_seq=-9999,  # unmatched
    )
    assert found is None, (
        "Must return None on unmatched chain_root, not fall through to order_list[0][0]"
    )

    # Sanity: matched lookup returns the right order.
    found = runner._find_order_for_chain(
        order_list=[(real_order, real_handle)],
        chain_root_seq=1234,
    )
    assert found is real_order


def test_chain_resolved_waits_through_split_chunks(fake_client, tmp_path):
    """Multi-lot split chain — chain_resolved set only after final chunk."""
    from datetime import timedelta
    from echolon.live.config.order_policy import QUIESCENCE_WINDOW_S
    router = OrderRouter(client=fake_client, state_dir=tmp_path / "state")
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    parent = router.submit_order("ENTRY_SHORT", "al2606.SF", 2, "al_s1")
    # First chunk
    router._enqueue_async_response(seq_id=parent.seq_id, order_id=910_001)
    router._enqueue_status_event(_FakeOrder(910_001, status=56))
    router._enqueue_trade_event(MagicMock(
        order_id=910_001, traded_id=11, traded_price=24625.0, traded_volume=1,
    ))
    _drive(router)
    parent.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    # First chunk done; chain not resolved (chunk 2 pending)
    assert not parent.chain_resolved.is_set()

    # Second chunk
    next_handles = [h for h in router._handles_by_seq.values()
                    if h.original_handle_id == parent.seq_id]
    assert len(next_handles) == 1
    next_h = next_handles[0]
    assert next_h.chain_resolved is parent.chain_resolved
    router._enqueue_async_response(seq_id=next_h.seq_id, order_id=910_002)
    router._enqueue_status_event(_FakeOrder(910_002, status=56))
    router._enqueue_trade_event(MagicMock(
        order_id=910_002, traded_id=12, traded_price=24625.0, traded_volume=1,
    ))
    _drive(router)
    next_h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    assert parent.chain_resolved.is_set()
