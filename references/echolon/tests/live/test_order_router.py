"""Tests for OrderRouter (Layer 2 watchdog + Amendments A, B, F, G).

Reference: docs/superpowers/designs/2026-05-07-miniqmt-architecture-and-order-logic.md
section 22.2 (Layer 2 watchdog test specifications) +
section 22.6 (Circuit breaker test specifications).

These tests run with a synchronous "manual-tick" watchdog driver — we
construct OrderRouter without starting the watchdog thread, then drain
events explicitly. This lets us advance time deterministically.
"""
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Stub xtquant before importing router.
for _mod_name in (
    "xtquant", "xtquant.xtconstant", "xtquant.xtdata",
    "xtquant.xttrader", "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402

from echolon.live.platforms.miniqmt.order_router import (  # noqa: E402
    OrderRouter,
    OrderState,
    OrderRouterTripped,
    RouterCallbacks,
    HealthMetrics,
)
from echolon.live.config.order_policy import (  # noqa: E402
    QUIESCENCE_WINDOW_S,
    DEADLINE_DEFAULT_S,
)


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


class _FakeOrder:
    def __init__(self, order_id, status, msg=""):
        self.order_id = order_id
        self.order_status = status
        self.status_msg = msg


class _FakeTrade:
    def __init__(self, order_id, trade_id, price, volume):
        self.order_id = order_id
        self.traded_id = trade_id
        self.traded_price = price
        self.traded_volume = volume


@pytest.fixture
def fake_client():
    """A fake MiniQMTClient that lets tests control submit/cancel returns."""
    client = MagicMock()
    client.set_callbacks = MagicMock()
    client.cancel_order = MagicMock(return_value=True)
    # Default: submit_order_async returns sequential seq_ids.
    client._next_seq = 1000
    def _submit(symbol, volume, price, order_type, intent, strategy_name):
        client._next_seq += 1
        return client._next_seq
    client.submit_order_async = MagicMock(side_effect=_submit)
    # Default: resolve_aggressive_price returns FIX_PRICE @ 24625.
    client.resolve_aggressive_price = MagicMock(return_value=(11, 24625.0))
    # Default: no tick snapshot (so Layer 4 splitter does not split).
    client._get_tick_snapshot = MagicMock(return_value=None)
    return client


@pytest.fixture
def router(fake_client, tmp_path):
    """Router without the watchdog thread started — tests drive it manually."""
    cb = RouterCallbacks()
    r = OrderRouter(
        client=fake_client,
        callbacks=cb,
        state_dir=tmp_path / "state",
        deadline_s=30.0,
    )
    return r


def _drive(router, ticks=1):
    """Manually advance the watchdog: drain events + run timer checks."""
    import queue as _queue
    for _ in range(ticks):
        with router._lock:
            try:
                while True:
                    event = router._event_queue.get_nowait()
                    router._process_event(event)
            except _queue.Empty:
                pass
            router._check_deadlines_and_quiescence()
            router._maybe_check_reset_flag()


# ---------------------------------------------------------------------------
# Submit + happy-path fill
# ---------------------------------------------------------------------------


def test_submit_returns_handle_with_seq(router, fake_client):
    h = router.submit_order(
        intent="ENTRY_SHORT", symbol="al2606.SF", volume=1, slot_id="al_s1",
    )
    assert h.seq_id > 0
    assert h.state == OrderState.SUBMITTED
    assert h.attempt == 1
    fake_client.submit_order_async.assert_called_once()


def test_async_response_links_seq_to_order_id(router):
    h = router.submit_order(
        intent="ENTRY_SHORT", symbol="al2606.SF", volume=1, slot_id="al_s1",
    )
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_001)
    _drive(router)
    assert h.qmt_order_id == 999_001
    assert router._handles_by_order[999_001] is h


def test_happy_fill(router):
    on_filled = MagicMock()
    router._callbacks.on_filled = on_filled

    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_002)
    router._enqueue_status_event(_FakeOrder(999_002, status=56))
    router._enqueue_trade_event(_FakeTrade(999_002, trade_id=1, price=24625.0, volume=1))
    _drive(router)

    # Force quiescence by aging last_event_at.
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    assert h.state == OrderState.TERMINAL_FILLED
    assert h.filled_volume == 1
    on_filled.assert_called_once_with(h)


# ---------------------------------------------------------------------------
# Watchdog deadline + cancel-and-resubmit
# ---------------------------------------------------------------------------


def test_watchdog_timeout_issues_cancel(router, fake_client):
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_003)
    _drive(router)

    # Force deadline expiry
    h.deadline_at = datetime.now() - timedelta(seconds=1)
    _drive(router)

    fake_client.cancel_order.assert_called_with(999_003)
    assert h.cancel_issued_at is not None


def test_resubmit_after_timeout_uses_attempt_2(router, fake_client):
    # Second submit returns a different seq_id; resolve_aggressive_price will
    # be called with attempt=2.
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_004)
    _drive(router)

    # Trigger deadline cancel
    h.deadline_at = datetime.now() - timedelta(seconds=1)
    _drive(router)
    # Deliver CANCELED status, then quiescence
    router._enqueue_status_event(_FakeOrder(999_004, status=54))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    # Second submit happened at attempt=2
    calls = fake_client.resolve_aggressive_price.call_args_list
    assert any(c.kwargs.get("attempt") == 2 or (len(c.args) >= 3 and c.args[2] == 2)
               for c in calls)
    # Second handle exists with attempt=2 and same intended_price
    new_handles = [hh for hh in router._handles_by_seq.values()
                   if hh.attempt == 2 and hh.original_handle_id == h.seq_id]
    assert len(new_handles) == 1
    assert new_handles[0].intended_price == h.intended_price  # Amendment E pin


# ---------------------------------------------------------------------------
# Race: cancel issued, late trade arrives within quiescence window
# ---------------------------------------------------------------------------


def test_race_cancel_then_late_fill(router):
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 2, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_005)
    _drive(router)

    # Deadline → cancel
    h.deadline_at = datetime.now() - timedelta(seconds=1)
    _drive(router)
    # CANCELED status → WINDING_DOWN
    router._enqueue_status_event(_FakeOrder(999_005, status=54))
    _drive(router)
    assert h.state == OrderState.WINDING_DOWN

    # Within quiescence window, a late trade arrives for partial fill of 1
    router._enqueue_trade_event(_FakeTrade(999_005, trade_id=42, price=24625.0, volume=1))
    _drive(router)
    assert h.filled_volume == 1
    # Quiescence resets — give it more time
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)
    assert h.state == OrderState.TERMINAL_CANCELED  # remainder=1 unfilled

    # Resubmit only handles the remaining 1 lot
    new_handles = [hh for hh in router._handles_by_seq.values() if hh.attempt == 2]
    assert len(new_handles) == 1
    assert new_handles[0].submitted_volume == 1


# ---------------------------------------------------------------------------
# Late trade after terminal — health metrics + warning
# ---------------------------------------------------------------------------


def test_late_trade_after_terminal_increments_health(router):
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_006)
    router._enqueue_status_event(_FakeOrder(999_006, status=54))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)
    assert h.state == OrderState.TERMINAL_CANCELED

    router._enqueue_trade_event(_FakeTrade(999_006, trade_id=99, price=24625.0, volume=1))
    _drive(router)
    assert router._health.quiescence_late_trade_count == 1
    assert h.filled_volume == 0  # frozen at terminal


# ---------------------------------------------------------------------------
# MAX_ATTEMPTS abandoned
# ---------------------------------------------------------------------------


def test_entry_max_attempts_abandons(router, fake_client):
    on_abandoned = MagicMock()
    router._callbacks.on_abandoned = on_abandoned

    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    current = h
    # Cycle through 3 attempts; each one timeouts → cancel → quiesce → resubmit
    next_order_id = 1000
    for _ in range(3):
        router._enqueue_async_response(seq_id=current.seq_id, order_id=next_order_id)
        _drive(router)
        current.deadline_at = datetime.now() - timedelta(seconds=1)
        _drive(router)
        router._enqueue_status_event(_FakeOrder(next_order_id, status=54))
        _drive(router)
        current.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
        _drive(router)
        next_order_id += 1
        # Find the next attempt's handle
        candidates = [hh for hh in router._handles_by_seq.values()
                      if hh.attempt == current.attempt + 1]
        if not candidates:
            break
        current = candidates[0]

    # original handle should be in archive marked ABANDONED somewhere along the chain
    abandoned = [hh for hh in router._terminal_archive.values()
                 if hh.state == OrderState.TERMINAL_ABANDONED]
    assert len(abandoned) >= 1
    on_abandoned.assert_called()


# ---------------------------------------------------------------------------
# Slippage cap aborts resubmit
# ---------------------------------------------------------------------------


def test_slippage_cap_aborts_resubmit(router, fake_client):
    # Set up: first submit at 24625, intended_price=24625
    # On resubmit, resolve returns 24000 — that's 2.5% off, > 2% ENTRY cap
    fake_client.resolve_aggressive_price.side_effect = [
        (11, 24625.0),  # initial submit
        (11, 24000.0),  # attempt 2 — out of band
    ]

    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_007)
    _drive(router)
    h.deadline_at = datetime.now() - timedelta(seconds=1)
    _drive(router)
    router._enqueue_status_event(_FakeOrder(999_007, status=54))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    # No attempt-2 handle in active map — should be ABANDONED
    new_handles = [hh for hh in router._handles_by_seq.values() if hh.attempt == 2]
    assert len(new_handles) == 0
    assert h.state == OrderState.TERMINAL_ABANDONED
    assert h.abandoned_reason == "slippage_cap"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def _make_router_with_low_thresholds(fake_client, tmp_path):
    """Construct router; we use the actual CIRCUIT_THRESHOLDS (2 consecutive)."""
    cb = RouterCallbacks()
    return OrderRouter(
        client=fake_client, callbacks=cb,
        state_dir=tmp_path / "state", deadline_s=30.0,
    )


def test_circuit_trips_on_consecutive_abandoned(fake_client, tmp_path):
    router = _make_router_with_low_thresholds(fake_client, tmp_path)
    on_trip = MagicMock()
    router._callbacks.on_circuit_tripped = on_trip

    # Force 2 consecutive abandons by triggering MAX_ATTEMPTS twice.
    for round_n in range(2):
        h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, f"slot_{round_n}")
        current = h
        next_order_id = 2000 + round_n * 10
        for _ in range(3):
            router._enqueue_async_response(seq_id=current.seq_id, order_id=next_order_id)
            _drive(router)
            current.deadline_at = datetime.now() - timedelta(seconds=1)
            _drive(router)
            router._enqueue_status_event(_FakeOrder(next_order_id, status=54))
            _drive(router)
            current.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
            _drive(router)
            next_order_id += 1
            cands = [hh for hh in router._handles_by_seq.values()
                     if hh.attempt == current.attempt + 1]
            if not cands:
                break
            current = cands[0]

    assert router._tripped
    on_trip.assert_called()


def test_tripped_router_refuses_new_submissions(router):
    router._tripped = True
    router._tripped_reason = "test_trip"
    with pytest.raises(OrderRouterTripped):
        router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")


def test_circuit_resets_via_flag_file(router, tmp_path):
    router._tripped = True
    router._tripped_reason = "test"
    router._tripped_at = datetime.now()
    flag = router._state_dir
    flag.mkdir(parents=True, exist_ok=True)
    (flag / "order_router_reset.flag").touch()

    # Force time-based eligibility for reset check
    router._last_reset_check_at = datetime.now() - timedelta(seconds=2)
    _drive(router)

    assert not router._tripped
    assert not (flag / "order_router_reset.flag").exists()


def test_circuit_state_persists_across_restart(fake_client, tmp_path):
    state_dir = tmp_path / "state"
    r1 = OrderRouter(client=fake_client, state_dir=state_dir, deadline_s=30.0)
    r1._trip("test_persistence")
    assert (state_dir / "order_router_state.json").exists()

    r2 = OrderRouter(client=fake_client, state_dir=state_dir, deadline_s=30.0)
    assert r2._tripped
    assert r2._tripped_reason == "test_persistence"


# ---------------------------------------------------------------------------
# Late-trade circuit breaker
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Watchdog scenarios — partial fill + deadline + callback queue
# ---------------------------------------------------------------------------


def test_partial_fill_then_deadline(router):
    """submit size=2 → status=55 partial + 1 lot filled → deadline → cancel
    → CANCELED → quiescence → resubmit remaining=1.
    """
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 2, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=998_001)
    router._enqueue_status_event(_FakeOrder(998_001, status=55))  # PARTIAL_FILLED
    router._enqueue_trade_event(_FakeTrade(998_001, trade_id=21, price=24625.0, volume=1))
    _drive(router)
    assert h.state == OrderState.PARTIAL_FILLED
    assert h.filled_volume == 1

    # Deadline → cancel → CANCELED → quiescence → resubmit
    h.deadline_at = datetime.now() - timedelta(seconds=1)
    _drive(router)
    router._enqueue_status_event(_FakeOrder(998_001, status=54))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    resubs = [hh for hh in router._handles_by_seq.values() if hh.attempt == 2]
    assert len(resubs) == 1
    assert resubs[0].submitted_volume == 1, "Resubmit must be for unfilled remainder only"


def test_callbacks_route_through_queue(router):
    """Verify callbacks NEVER mutate _handles directly — only via the queue."""
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")

    # Callback fires — but watchdog hasn't drained yet.
    router._enqueue_status_event(_FakeOrder(h.seq_id + 99999, status=54))
    # _handles unchanged because the event_id in the callback is wrong AND
    # because we haven't drained the queue.
    pre_drain_state = h.state

    # Drain the queue.
    _drive(router)
    # Wrong order_id callback got dropped (logged warning, no mutation).
    assert h.state == pre_drain_state == OrderState.SUBMITTED


# ---------------------------------------------------------------------------
# Circuit breaker — in-flight handles complete after trip
# ---------------------------------------------------------------------------


def test_circuit_inflight_orders_complete_after_trip(router):
    """When the circuit trips, in-flight handles MUST still complete
    normally (the watchdog continues; cancels and resubmits are for
    currently-tracked orders only). New submits are refused."""
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=997_001)
    _drive(router)

    # Trip the circuit while h is in flight.
    router._trip("test_trip")
    assert router.is_tripped

    # Now fill h: the watchdog should still process events and reach terminal.
    router._enqueue_status_event(_FakeOrder(997_001, status=56))
    router._enqueue_trade_event(_FakeTrade(997_001, trade_id=31, price=24625.0, volume=1))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    assert h.state == OrderState.TERMINAL_FILLED
    assert h.filled_volume == 1

    # New submits MUST be refused.
    with pytest.raises(__import__(
        "echolon.live.platforms.miniqmt.order_router", fromlist=["OrderRouterTripped"]
    ).OrderRouterTripped):
        router.submit_order("ENTRY_LONG", "al2606.SF", 1, "al_s2")


# ---------------------------------------------------------------------------
# Layer 4 splitter
# ---------------------------------------------------------------------------


def test_no_split_when_visible_top1_sufficient(router, fake_client):
    fake_client._get_tick_snapshot.return_value = {
        "askPrice": [24650.0], "bidPrice": [24645.0],
        "askVolume": [10], "bidVolume": [10], "lastPrice": 24648.0,
    }
    chunks = router._maybe_split("ENTRY_SHORT", "al2606.SF", volume=2)
    assert chunks == [2]


def test_split_when_volume_exceeds_top1(router, fake_client):
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    chunks = router._maybe_split("ENTRY_SHORT", "al2606.SF", volume=3)
    # top1=1, chunk_size = max(1, 1//2)=1, so 3 chunks of 1
    assert chunks == [1, 1, 1]


def test_splitter_fires_first_chunk_and_holds_rest(router, fake_client):
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 2, "al_s1")
    # First chunk submitted with size=1, not 2.
    assert h.submitted_volume == 1
    # SplitSequence registered with [1] remaining.
    seq = router._split_sequences.get(h.seq_id)
    assert seq is not None
    assert seq.chunks == [1]


def test_splitter_fires_next_after_terminal_filled(router, fake_client):
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 2, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_010)
    router._enqueue_status_event(_FakeOrder(999_010, status=56))
    router._enqueue_trade_event(_FakeTrade(999_010, trade_id=1, price=24625.0, volume=1))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)
    # First chunk filled — second chunk should now be in active map.
    next_handles = [hh for hh in router._handles_by_seq.values()
                    if hh.original_handle_id == h.seq_id]
    assert len(next_handles) == 1
    assert next_handles[0].submitted_volume == 1


def test_splitter_abort_cascade_on_abandon(router, fake_client):
    """TERMINAL_ABANDONED on a sub-order MUST abort the whole sequence
    even when the partial-fill fraction is high. Per design §21.11."""
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    # Force MAX_ATTEMPTS=1 so timeout → immediate abandoned (instead of resubmit).
    from echolon.live.config import order_policy
    original_max = order_policy.MAX_ATTEMPTS_BY_CLASS["ENTRY"]
    order_policy.MAX_ATTEMPTS_BY_CLASS["ENTRY"] = 1
    try:
        h = router.submit_order("ENTRY_SHORT", "al2606.SF", 3, "al_s1")
        # Chunk 1 size=1; sequence has [1, 1] remaining
        assert router._split_sequences[h.seq_id].chunks == [1, 1]

        # Trigger abandonment of chunk 1 (timeout → CANCELED → max_attempts).
        router._enqueue_async_response(seq_id=h.seq_id, order_id=999_020)
        _drive(router)
        h.deadline_at = datetime.now() - timedelta(seconds=1)
        _drive(router)
        router._enqueue_status_event(_FakeOrder(999_020, status=54))
        _drive(router)
        h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
        _drive(router)

        # Sequence MUST be aborted; no chunk-2 fired.
        assert h.seq_id not in router._split_sequences
        next_handles = [hh for hh in router._handles_by_seq.values()
                        if hh.original_handle_id == h.seq_id]
        assert len(next_handles) == 0, "Abort cascade: no sub-orders after abandonment"
    finally:
        order_policy.MAX_ATTEMPTS_BY_CLASS["ENTRY"] = original_max


def test_splitter_partial_fill_rolls_remainder_into_next_chunk(router, fake_client):
    """When chunk N has >=50% partial-fill at TERMINAL_CANCELED, the
    unfilled remainder rolls forward into chunk N+1's size."""
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [2], "bidVolume": [2],
    }
    # volume=4, top1=2 → chunks = [2, 2] (chunk_size=top1//2=1, but volume=4 → 4 chunks of 1).
    # Adjust top1 to make chunks = [2, 2].
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [4], "bidVolume": [4],
    }
    # With top1=4 and volume=6: top1<volume so split. chunk_size=max(1, 4//2)=2 → [2,2,2].
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 6, "al_s1")
    assert router._split_sequences[h.seq_id].chunks == [2, 2]

    # Chunk 1 (size=2) fills 1 of 2 (50%) then CANCELED.
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_030)
    router._enqueue_trade_event(_FakeTrade(999_030, trade_id=10, price=24625.0, volume=1))
    router._enqueue_status_event(_FakeOrder(999_030, status=54))
    _drive(router)
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    # Chunk 2 should fire with rolled-over remainder: 2 (original next) + 1 (rollover) = 3.
    next_handles = [hh for hh in router._handles_by_seq.values()
                    if hh.original_handle_id == h.seq_id]
    assert len(next_handles) == 1
    assert next_handles[0].submitted_volume == 3, (
        f"Expected next chunk size=3 (2 next + 1 unfilled remainder); "
        f"got {next_handles[0].submitted_volume}"
    )


# ---------------------------------------------------------------------------
# Layer 5 BandGuard
# ---------------------------------------------------------------------------


def test_band_guard_refuses_buy_above_upper(router, fake_client):
    """If resolved price > upper band, BandGuard raises OrderRouterError."""
    from echolon.live.platforms.miniqmt import order_router as router_mod

    fake_client.resolve_aggressive_price.return_value = (11, 1_000_000.0)
    # Stub get_instrument_meta to give a real settlement
    with patch.object(router_mod, "get_instrument_meta", return_value=router_mod._InstrumentMeta(
        price_tick=5.0, settlement=24700.0, band_pct=0.07,
    )):
        with pytest.raises(router_mod.OrderRouterError) as exc:
            router.submit_order("ENTRY_LONG", "al2606.SF", 1, "al_s1")
    assert "exceeds" in str(exc.value)


def test_band_guard_passes_within_band(router, fake_client):
    from echolon.live.platforms.miniqmt import order_router as router_mod

    fake_client.resolve_aggressive_price.return_value = (11, 24700.0)
    with patch.object(router_mod, "get_instrument_meta", return_value=router_mod._InstrumentMeta(
        price_tick=5.0, settlement=24700.0, band_pct=0.07,
    )):
        h = router.submit_order("ENTRY_LONG", "al2606.SF", 1, "al_s1")
    assert h.state == OrderState.SUBMITTED


def test_band_guard_refuses_sell_below_lower(router, fake_client):
    """If resolved SELL price < lower band, BandGuard raises OrderRouterError."""
    from echolon.live.platforms.miniqmt import order_router as router_mod

    fake_client.resolve_aggressive_price.return_value = (11, 1.0)  # absurdly low
    with patch.object(router_mod, "get_instrument_meta", return_value=router_mod._InstrumentMeta(
        price_tick=5.0, settlement=24700.0, band_pct=0.07,
    )):
        with pytest.raises(router_mod.OrderRouterError) as exc:
            router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    assert "below" in str(exc.value)


def test_band_guard_per_instrument_band_lookup():
    """BandGuard uses the per-instrument band_pct (au=5%, al=7%, etc)."""
    from echolon.live.platforms.miniqmt import order_router as router_mod
    from echolon.live.config.shfe_bands import band_pct_for
    assert band_pct_for("au2606.SF") == 0.05
    assert band_pct_for("al2606.SF") == 0.07
    # Unknown instrument falls to default
    assert band_pct_for("xyz2606.SF") == 0.07  # DEFAULT_BAND_PCT

    # Verify is_within_band uses the right band per product.
    # gold 'au': settlement=600, band=5% → upper = 600 * 1.05 * 0.99 = 623.7
    with patch.object(router_mod, "get_instrument_meta", return_value=router_mod._InstrumentMeta(
        price_tick=0.05, settlement=600.0, band_pct=0.05,
    )):
        ok, _ = router_mod.is_within_band("au2606.SF", "ENTRY_LONG", 624.0)
        assert not ok  # 624 > 623.7
        ok, _ = router_mod.is_within_band("au2606.SF", "ENTRY_LONG", 620.0)
        assert ok


def test_band_guard_skips_when_settlement_unknown(router, fake_client):
    """No settlement (xtdata returned 0) → BandGuard is a no-op."""
    from echolon.live.platforms.miniqmt import order_router as router_mod

    fake_client.resolve_aggressive_price.return_value = (11, 24700.0)
    with patch.object(router_mod, "get_instrument_meta", return_value=router_mod._InstrumentMeta(
        price_tick=5.0, settlement=0.0, band_pct=0.07,
    )):
        h = router.submit_order("ENTRY_LONG", "al2606.SF", 1, "al_s1")
    assert h.state == OrderState.SUBMITTED


# ---------------------------------------------------------------------------
# Original tests continue
# ---------------------------------------------------------------------------


def test_immediate_rejection_with_split_does_not_orphan_sequence(fake_client, tmp_path):
    """Regression — when broker rejects (seq_id=0) AND volume would split,
    no SplitSequence may be registered (otherwise it leaks forever)."""
    fake_client.submit_order_async = MagicMock(return_value=0)  # immediate reject
    fake_client._get_tick_snapshot.return_value = {
        "askVolume": [1], "bidVolume": [1],
    }
    router = OrderRouter(client=fake_client, state_dir=tmp_path / "state")
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 3, "al_s1")
    assert h.state == OrderState.TERMINAL_REJECTED
    # No active SplitSequence may remain.
    assert len(router._split_sequences) == 0, (
        f"Orphan split sequence after immediate-rejection: "
        f"{list(router._split_sequences.keys())}"
    )
    # chain_resolved must already be set.
    assert h.chain_resolved.is_set()


def test_reconcile_fills_from_broker_recovers_dropped_callback(router, fake_client):
    """If a trade callback was dropped, query_stock_trades sweep at
    quiescence should still recover the fill."""
    h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, "al_s1")
    router._enqueue_async_response(seq_id=h.seq_id, order_id=999_500)
    # Status arrives but trade callback is silently dropped.
    router._enqueue_status_event(_FakeOrder(999_500, status=56))
    _drive(router)

    # query_stock_trades returns the missed trade.
    fake_client.query_stock_trades = MagicMock(return_value=[
        {"order_id": 999_500, "traded_id": 77, "traded_price": 24625.0, "traded_volume": 1},
    ])

    # Quiescence triggers _transition_to_terminal which calls reconcile.
    h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
    _drive(router)

    assert h.state == OrderState.TERMINAL_FILLED, (
        f"Reconcile must recover the fill; got {h.state}"
    )
    assert h.filled_volume == 1
    assert 77 in h.seen_trade_ids


def test_invalid_volume_rejected_at_submit_gate(router):
    """submit_order with non-positive int volume should raise."""
    from echolon.live.platforms.miniqmt.order_router import OrderRouterError
    with pytest.raises(OrderRouterError):
        router.submit_order("ENTRY_SHORT", "al2606.SF", 0, "al_s1")
    with pytest.raises(OrderRouterError):
        router.submit_order("ENTRY_SHORT", "al2606.SF", -1, "al_s1")


def test_reset_cycle_metrics_clears_health(router):
    """reset_cycle_metrics resets counters but NOT the tripped flag."""
    router._health.terminal_filled = 100
    router._health.terminal_abandoned = 5
    router._tripped = True
    router._tripped_reason = "preserve me"

    router.reset_cycle_metrics()

    assert router._health.terminal_filled == 0
    assert router._health.terminal_abandoned == 0
    # Tripped flag survives — operator must reset that explicitly.
    assert router._tripped
    assert router._tripped_reason == "preserve me"


def test_late_trade_count_trips_circuit(router):
    # Need 3 late-trade events (one for each of 3 different terminated orders).
    for i in range(3):
        h = router.submit_order("ENTRY_SHORT", "al2606.SF", 1, f"slot_{i}")
        oid = 3000 + i
        router._enqueue_async_response(seq_id=h.seq_id, order_id=oid)
        router._enqueue_status_event(_FakeOrder(oid, status=54))
        _drive(router)
        h.last_event_at = datetime.now() - timedelta(seconds=QUIESCENCE_WINDOW_S + 0.5)
        _drive(router)
        # Late trade arrives
        router._enqueue_trade_event(_FakeTrade(oid, trade_id=8000 + i, price=24625.0, volume=1))
        _drive(router)

    assert router._tripped
    assert router._tripped_reason == "late_trade_rate"
