"""OrderRouter — robust order submission with watchdog + recovery.

Implements design sections 11-19 (Layer 2 watchdog, state machine,
circuit breaker, ABANDONED-EXIT recovery wiring). Replaces the pattern
of "submit-and-forget" with a state-machine-driven router that:

- Tracks every submitted order through PENDING -> SUBMITTED ->
  WINDING_DOWN -> TERMINAL_*.
- Cancels-and-resubmits unfilled orders past their deadline, with
  per-attempt buffer escalation.
- Bounds resubmits by MAX_ATTEMPTS_BY_CLASS and slippage cap pinned
  to intended price (Amendment E).
- Notifies the runner on TERMINAL events so it can book fills and
  set pending_exit_intent for ABANDONED-EXIT recovery (Amendment B).
- Trips an execution-quality circuit breaker on consecutive abandons,
  excessive rejection rate, or late-trade events (Amendment G).

Threading model (Amendment F — single-writer):
- All callbacks (status, trade, async_response) push typed events
  onto an internal queue. They never touch _handles.
- A single watchdog thread drains the queue, advances state, fires
  cancels and resubmits.
- External readers (e.g. portfolio for ops queries) acquire the
  RLock to read _handles.

Reference: docs/superpowers/designs/2026-05-07-miniqmt-architecture-and-order-logic.md
"""

import json
import logging
import math
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple

from xtquant import xtconstant, xtdata

from ...config.order_policy import (
    BUFFER_TICKS_BY_ATTEMPT,
    CIRCUIT_THRESHOLDS,
    DAILY_BAND_SAFETY_MARGIN,
    DEADLINE_DEFAULT_S,
    DEFAULT_BUFFER_TICKS,
    KILL_BAND_FRACTION,
    MAX_ATTEMPTS_BY_CLASS,
    MAX_SLIPPAGE_PCT_BY_CLASS,
    MIN_PARTIAL_FILL_FRACTION,
    QUIESCENCE_WINDOW_S,
    TICK_SNAPSHOT_MAX_AGE_S,
    WATCHDOG_TICK_S,
)
from ...config.shfe_bands import band_pct_for, product_code

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class OrderState(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial"
    WINDING_DOWN = "winding_down"
    TERMINAL_FILLED = "terminal_filled"
    TERMINAL_CANCELED = "terminal_canceled"
    TERMINAL_REJECTED = "terminal_rejected"
    TERMINAL_ABANDONED = "terminal_abandoned"


TERMINAL_STATES = {
    OrderState.TERMINAL_FILLED,
    OrderState.TERMINAL_CANCELED,
    OrderState.TERMINAL_REJECTED,
    OrderState.TERMINAL_ABANDONED,
}

BUY_INTENTS = {"ENTRY_LONG", "EXIT_SHORT", "ROLLOVER_OPEN"}
SELL_INTENTS = {"ENTRY_SHORT", "EXIT_LONG", "ROLLOVER_CLOSE", "FORCED_EXIT"}

RECOVERY_CLASS: Dict[str, str] = {
    "ENTRY_LONG": "ENTRY",
    "ENTRY_SHORT": "ENTRY",
    "EXIT_LONG": "EXIT",
    "EXIT_SHORT": "EXIT",
    "ROLLOVER_OPEN": "ROLLOVER_OPEN",
    "ROLLOVER_CLOSE": "ROLLOVER_CLOSE",
    "FORCED_EXIT": "FORCED_EXIT",
}

EXIT_CLASS_INTENTS = {"EXIT_LONG", "EXIT_SHORT", "ROLLOVER_CLOSE", "FORCED_EXIT"}


class OrderRouterTripped(Exception):
    """Raised by submit_order when the router's circuit breaker is tripped."""


class OrderRouterError(Exception):
    """Generic router-side error (precondition failure, etc)."""


@dataclass
class OrderEvent:
    """Single typed event from broker callback or watchdog timer."""
    kind: Literal["status", "trade", "async_response"]
    timestamp: datetime
    # Discriminated by kind
    seq_id: Optional[int] = None        # async_response only
    order_id: Optional[int] = None      # status, trade, async_response
    status: Optional[int] = None        # status only — xtconstant 48..57
    status_msg: str = ""
    trade_id: Optional[int] = None      # trade only
    trade_price: Optional[float] = None
    trade_volume: Optional[int] = None


@dataclass
class OrderHandle:
    """Lifecycle record for one submission attempt."""
    seq_id: int
    qmt_order_id: Optional[int] = None
    slot_id: str = ""
    symbol: str = ""

    intent: str = "ENTRY_LONG"
    recovery_class: str = "ENTRY"

    intended_price: float = 0.0
    submitted_volume: int = 0
    submitted_price: float = 0.0
    submitted_at: Optional[datetime] = None

    attempt: int = 1
    original_handle_id: Optional[int] = None

    state: OrderState = OrderState.PENDING
    last_event_at: datetime = field(default_factory=datetime.now)
    deadline_at: Optional[datetime] = None
    cancel_issued_at: Optional[datetime] = None

    seen_trade_ids: Set[int] = field(default_factory=set)
    filled_volume: int = 0
    filled_avg_price: float = 0.0

    last_status: int = 0
    last_status_msg: str = ""

    abandoned_reason: Optional[str] = None

    # Chain resolution — shared across all handles in the same retry/split chain.
    # The PARENT (initial submit) creates the threading.Event; resubmit and
    # split-chunk handles inherit the same event reference. The router sets
    # the event when no further handle will be created for the chain.
    # The runner waits on this to block until full resolution.
    chain_resolved: Optional[Any] = None  # threading.Event, but Any to avoid import in dataclass field metadata


@dataclass
class SplitSequence:
    """Layer 4 sequential-with-confirm splitter state.

    One per parent intent. ``chunks`` is the queue of remaining
    sub-order sizes to fire. The router fires the next chunk only after
    the current one reaches a TERMINAL_FILLED (or PARTIAL above the
    fraction threshold) — never in parallel.
    """
    parent_handle_id: int
    chunks: List[int] = field(default_factory=list)
    fired_handle_ids: List[int] = field(default_factory=list)
    total_filled: int = 0
    abandoned: bool = False
    intent: str = ""
    symbol: str = ""
    slot_id: str = ""
    intended_price: float = 0.0


@dataclass
class HealthMetrics:
    """Rolling per-cycle execution-quality stats."""
    cycle_started_at: datetime = field(default_factory=datetime.now)
    submitted: int = 0
    terminal_filled: int = 0
    terminal_partial: int = 0
    terminal_abandoned: int = 0
    terminal_rejected: int = 0
    consecutive_abandoned: int = 0
    quiescence_late_trade_count: int = 0


# ---------------------------------------------------------------------------
# Runner-callback contract
# ---------------------------------------------------------------------------


@dataclass
class RouterCallbacks:
    """Hooks the runner registers to be notified of terminal events."""
    on_filled: Optional[Callable[[OrderHandle], None]] = None
    on_partial: Optional[Callable[[OrderHandle], None]] = None
    on_abandoned: Optional[Callable[[OrderHandle, int, str], None]] = None
    on_rejected: Optional[Callable[[OrderHandle], None]] = None
    on_circuit_tripped: Optional[Callable[[str], None]] = None


# ---------------------------------------------------------------------------
# OrderRouter
# ---------------------------------------------------------------------------


class OrderRouter:
    """Single-writer order router with watchdog + recovery.

    See module docstring for threading model.
    """

    def __init__(
        self,
        client: "MiniQMTClient",                # forward-typed; avoids import cycle
        callbacks: Optional[RouterCallbacks] = None,
        state_dir: Optional[Path] = None,
        deadline_s: float = DEADLINE_DEFAULT_S,
        strategy_name: str = "DolphinQuantStrategy",
    ):
        self._client = client
        self._callbacks = callbacks or RouterCallbacks()
        self._state_dir = Path(state_dir) if state_dir is not None else None
        self._deadline_s = deadline_s
        self._strategy_name = strategy_name

        # Single-writer storage. Lock protects all _handles* and _split* state.
        self._lock = threading.RLock()
        self._handles_by_seq: Dict[int, OrderHandle] = {}
        self._handles_by_order: Dict[int, OrderHandle] = {}
        self._terminal_archive: Dict[int, OrderHandle] = {}

        # Event queue — callbacks push, watchdog drains.
        self._event_queue: "queue.Queue[OrderEvent]" = queue.Queue()

        # Health + circuit
        self._health = HealthMetrics()
        self._tripped = False
        self._tripped_reason = ""
        self._tripped_at: Optional[datetime] = None

        # Reset-flag-file polling cadence (1s).
        self._last_reset_check_at: datetime = datetime.now()

        # Per-product tick + settlement caching is module-level
        # (see ``get_instrument_meta``); shared across the whole process.

        # Layer 4 splitter — keyed by parent_handle_id (the first sub-order's seq).
        self._split_sequences: Dict[int, SplitSequence] = {}

        # Watchdog thread.
        self._stop = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None

        # Wire client callbacks to enqueue methods.
        client.set_callbacks(
            order_callback=self._enqueue_status_event,
            trade_callback=self._enqueue_trade_event,
            async_response_callback=self._enqueue_async_response,
        )

        self._load_persisted_state()

    # ---- Public API --------------------------------------------------------

    def start(self) -> None:
        """Start the watchdog thread."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._run_watchdog, daemon=True, name="OrderWatchdog",
        )
        self._watchdog_thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the watchdog thread; in-flight orders are NOT cancelled."""
        self._stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=timeout)

    def submit_order(
        self,
        intent: str,
        symbol: str,
        volume: int,
        slot_id: str,
        intended_price: Optional[float] = None,
        force_price: Optional[float] = None,
        force_price_type: Optional[int] = None,
        atr_ticks: int = 0,
        enable_splitter: bool = True,
    ) -> OrderHandle:
        """Submit a new order. Returns the first attempt's handle.

        force_price overrides the resolved aggressive price (used for
        kill-at-band-edge recovery in Amendment B).

        atr_ticks (Layer 3) is added to the static buffer in
        resolve_aggressive_price for an ATR-aware extra cushion.

        enable_splitter (Layer 4) determines whether multi-lot orders are
        split into sequential sub-orders when visible top1 is thin.

        Raises OrderRouterTripped if the circuit breaker is tripped.
        Raises OrderRouterError if BandGuard rejects the price.
        """
        with self._lock:
            if self._tripped:
                raise OrderRouterTripped(
                    f"OrderRouter tripped: {self._tripped_reason}; "
                    f"refusing new submissions"
                )

            # Defensive: reject obviously-invalid volumes at the gate so
            # the broker doesn't see them.
            if not isinstance(volume, int) or volume <= 0:
                raise OrderRouterError(
                    f"submit_order: volume must be a positive int, got {volume!r}"
                )

            if force_price is not None:
                price_type = force_price_type or xtconstant.FIX_PRICE
                price = force_price
            else:
                price_type, price = self._client.resolve_aggressive_price(
                    symbol, intent, attempt=1, atr_ticks=atr_ticks,
                )

            if intended_price is None:
                intended_price = price if price > 0 else 0.0

            # Layer 5 — BandGuard. Refuse to submit prices outside the
            # exchange-acceptance band (defensive; almost never trips for
            # normal flows but catches Layer 3 ATR overshoots).
            if price > 0:
                ok, reason = is_within_band(symbol, intent, price)
                if not ok:
                    raise OrderRouterError(
                        f"BandGuard refused submit: {reason}"
                    )

            # Layer 4 — splitter. Decide chunks based on visible top1.
            chunks = [volume]
            if enable_splitter and force_price is None:
                chunks = self._maybe_split(intent, symbol, volume)

            first_chunk = chunks[0]

            seq_id = self._client.submit_order_async(
                symbol=symbol,
                volume=first_chunk,
                price=price,
                order_type="MARKET" if force_price is None else "LIMIT",
                intent=intent,
                strategy_name=self._strategy_name,
            )

            handle = OrderHandle(
                seq_id=seq_id if seq_id else -abs(id(self)) % 10_000_000,
                slot_id=slot_id,
                symbol=symbol,
                intent=intent,
                recovery_class=RECOVERY_CLASS.get(intent, "ENTRY"),
                intended_price=float(intended_price),
                submitted_volume=int(first_chunk),
                submitted_price=float(price) if price > 0 else 0.0,
                submitted_at=datetime.now(),
                attempt=1,
                state=OrderState.SUBMITTED if seq_id else OrderState.PENDING,
                deadline_at=datetime.now() + timedelta(seconds=self._deadline_s),
                chain_resolved=threading.Event(),  # parent owns the chain event
            )

            # If broker immediately rejected (returned no seq_id), short-circuit
            # BEFORE registering a SplitSequence — otherwise we'd orphan the
            # sequence (no callbacks ever fire to advance it).
            if not seq_id:
                handle.state = OrderState.TERMINAL_REJECTED
                handle.last_status_msg = "submit_order_async returned no seq_id"
                self._health.terminal_rejected += 1
                self._health.consecutive_abandoned = 0
                self._terminal_archive[handle.seq_id] = handle
                self._notify(self._callbacks.on_rejected, handle)
                if handle.chain_resolved is not None:
                    handle.chain_resolved.set()
                return handle

            # Broker accepted — register active state, and SplitSequence if applicable.
            self._handles_by_seq[handle.seq_id] = handle
            if len(chunks) > 1:
                self._split_sequences[handle.seq_id] = SplitSequence(
                    parent_handle_id=handle.seq_id,
                    chunks=chunks[1:],   # remaining sub-orders to fire
                    fired_handle_ids=[handle.seq_id],
                    intent=intent, symbol=symbol, slot_id=slot_id,
                    intended_price=float(intended_price),
                )
                logger.info(
                    "Order SPLIT: parent=%d chunks=%s (first=%d, remaining=%s)",
                    handle.seq_id, [first_chunk] + chunks[1:],
                    first_chunk, chunks[1:],
                )
            self._health.submitted += 1
            logger.info(
                "Order submitted seq=%d slot=%s %s %s vol=%d price=%.2f attempt=%d",
                handle.seq_id, slot_id, intent, symbol, volume, price, handle.attempt,
            )
            return handle

    def cancel_handle(self, handle: OrderHandle) -> bool:
        """Externally request cancel (e.g. operator-driven). Cancel is
        best-effort; the broker callback drives the actual state change."""
        if handle.qmt_order_id is None:
            return False
        return bool(self._client.cancel_order(handle.qmt_order_id))

    def reset_circuit(self, reason: str = "operator_reset") -> None:
        """Clear the tripped flag (operator action)."""
        with self._lock:
            if not self._tripped:
                return
            logger.warning(
                "OrderRouter circuit RESET (was: %s); operator: %s",
                self._tripped_reason, reason,
            )
            self._tripped = False
            self._tripped_reason = ""
            self._tripped_at = None
            self._health = HealthMetrics()
            self._persist_circuit_state()

    def reset_cycle_metrics(self) -> None:
        """Reset per-cycle health metrics. Called by the runner at the
        start of each daily cycle so that abandon/reject *rates* are
        computed against the current cycle's submissions, not lifetime
        counters that grow until they drown out fresh failures.

        The circuit ``_tripped`` flag is preserved (operator must
        explicitly reset that via reset_circuit / flag file).
        """
        with self._lock:
            self._health = HealthMetrics()

    def trip_circuit(self, reason: str) -> None:
        """Trip the persisted circuit breaker from an external safety check.

        Used by portfolio-level risk overlays so all submission blocking and
        restart persistence stay owned by the OrderRouter circuit mechanism.
        """
        with self._lock:
            if self._tripped:
                return
            self._trip(reason)

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def tripped_reason(self) -> str:
        return self._tripped_reason

    def get_handle_by_seq(self, seq_id: int) -> Optional[OrderHandle]:
        with self._lock:
            return self._handles_by_seq.get(seq_id) or self._terminal_archive.get(seq_id)

    # ---- Callback enqueue (called from xtquant callback thread) -----------

    def _enqueue_status_event(self, order: Any) -> None:
        try:
            self._event_queue.put(OrderEvent(
                kind="status",
                timestamp=datetime.now(),
                order_id=int(getattr(order, "order_id", 0)),
                status=int(getattr(order, "order_status", 0)),
                status_msg=str(getattr(order, "status_msg", "")),
            ))
        except Exception as exc:
            logger.error("Failed to enqueue status event: %s", exc)

    def _enqueue_trade_event(self, trade: Any) -> None:
        try:
            self._event_queue.put(OrderEvent(
                kind="trade",
                timestamp=datetime.now(),
                order_id=int(getattr(trade, "order_id", 0)),
                trade_id=int(getattr(trade, "traded_id", getattr(trade, "trade_id", 0))),
                trade_price=float(getattr(trade, "traded_price", 0.0)),
                trade_volume=int(getattr(trade, "traded_volume", 0)),
            ))
        except Exception as exc:
            logger.error("Failed to enqueue trade event: %s", exc)

    def _enqueue_async_response(self, seq_id: int, order_id: int) -> None:
        try:
            self._event_queue.put(OrderEvent(
                kind="async_response",
                timestamp=datetime.now(),
                seq_id=int(seq_id),
                order_id=int(order_id),
            ))
        except Exception as exc:
            logger.error("Failed to enqueue async_response: %s", exc)

    # ---- Watchdog loop -----------------------------------------------------

    def _run_watchdog(self) -> None:
        logger.info("OrderRouter watchdog started")
        while not self._stop.is_set():
            event: Optional[OrderEvent]
            try:
                event = self._event_queue.get(timeout=WATCHDOG_TICK_S)
            except queue.Empty:
                event = None

            with self._lock:
                if event is not None:
                    self._process_event(event)
                self._check_deadlines_and_quiescence()
                self._maybe_check_reset_flag()

        logger.info("OrderRouter watchdog stopped")

    def _process_event(self, event: OrderEvent) -> None:
        if event.kind == "async_response":
            self._handle_async_response(event)
            return

        # status / trade events are keyed by order_id (post-resolution).
        handle = self._handles_by_order.get(event.order_id)
        if handle is None:
            archived = self._terminal_archive.get(event.order_id)
            if archived is not None:
                self._handle_late_event_after_terminal(archived, event)
            else:
                logger.warning(
                    "Event for unknown order_id=%s kind=%s — dropped",
                    event.order_id, event.kind,
                )
            return

        handle.last_event_at = event.timestamp

        if event.kind == "status":
            self._handle_status(handle, event)
        elif event.kind == "trade":
            self._handle_trade(handle, event)

    def _handle_async_response(self, event: OrderEvent) -> None:
        handle = self._handles_by_seq.get(event.seq_id)
        if handle is None:
            logger.warning("async_response for unknown seq=%s", event.seq_id)
            return
        handle.qmt_order_id = event.order_id
        self._handles_by_order[event.order_id] = handle

    def _handle_status(self, handle: OrderHandle, event: OrderEvent) -> None:
        handle.last_status = event.status or 0
        handle.last_status_msg = event.status_msg

        # 53/54 = canceled; 55 = partial-filled; 56 = filled; 57 = rejected
        # (xtconstant uses these integer codes; we match by integer for
        # robustness across xtconstant versions)
        if event.status == 55:  # PARTIAL_FILLED
            if handle.state == OrderState.SUBMITTED:
                handle.state = OrderState.PARTIAL_FILLED
            return

        if event.status in (54, 53):  # CANCELED / PARTIAL_CANCELED
            if handle.state not in TERMINAL_STATES and handle.state != OrderState.WINDING_DOWN:
                handle.state = OrderState.WINDING_DOWN
            return

        if event.status == 56:  # FILLED
            if handle.state not in TERMINAL_STATES and handle.state != OrderState.WINDING_DOWN:
                handle.state = OrderState.WINDING_DOWN
            return

        if event.status == 57:  # REJECTED
            if handle.state not in TERMINAL_STATES and handle.state != OrderState.WINDING_DOWN:
                handle.state = OrderState.WINDING_DOWN
            return

    def _handle_trade(self, handle: OrderHandle, event: OrderEvent) -> None:
        if event.trade_id and event.trade_id in handle.seen_trade_ids:
            return  # dedupe
        if event.trade_id:
            handle.seen_trade_ids.add(event.trade_id)
        vol = event.trade_volume or 0
        price = event.trade_price or 0.0
        if vol <= 0:
            return
        prev_v = handle.filled_volume
        prev_p = handle.filled_avg_price
        new_v = prev_v + vol
        handle.filled_avg_price = (prev_v * prev_p + vol * price) / max(1, new_v)
        handle.filled_volume = new_v
        if handle.state == OrderState.SUBMITTED:
            handle.state = OrderState.PARTIAL_FILLED

    def _handle_late_event_after_terminal(self, handle: OrderHandle, event: OrderEvent) -> None:
        """Events arriving for an order already in TERMINAL — log + alert."""
        if event.kind != "trade":
            return
        if event.trade_id and event.trade_id in handle.seen_trade_ids:
            return
        self._health.quiescence_late_trade_count += 1
        logger.warning(
            "Late trade after terminal: order_id=%s trade_id=%s vol=%s price=%s; "
            "filled_volume frozen at %d (broker reconciliation will catch it)",
            event.order_id, event.trade_id, event.trade_volume, event.trade_price,
            handle.filled_volume,
        )
        self._check_circuit()

    # ---- Deadline + quiescence --------------------------------------------

    def _check_deadlines_and_quiescence(self) -> None:
        now = datetime.now()
        for handle in list(self._handles_by_seq.values()):
            # Deadline check
            if (handle.state in (OrderState.SUBMITTED, OrderState.PARTIAL_FILLED)
                    and handle.deadline_at is not None
                    and now >= handle.deadline_at):
                self._issue_cancel(handle)
                handle.deadline_at = None  # one-shot

            # Quiescence check
            if (handle.state == OrderState.WINDING_DOWN
                    and (now - handle.last_event_at).total_seconds() >= QUIESCENCE_WINDOW_S):
                self._transition_to_terminal(handle)

    def _issue_cancel(self, handle: OrderHandle) -> None:
        if handle.qmt_order_id is None:
            logger.warning(
                "Deadline reached for seq=%s but no qmt_order_id yet; cannot cancel",
                handle.seq_id,
            )
            return
        handle.cancel_issued_at = datetime.now()
        try:
            self._client.cancel_order(handle.qmt_order_id)
            logger.info(
                "Cancel issued seq=%s order_id=%s after deadline (state=%s, filled=%d/%d)",
                handle.seq_id, handle.qmt_order_id, handle.state.value,
                handle.filled_volume, handle.submitted_volume,
            )
        except Exception as exc:
            logger.error(
                "Cancel failed seq=%s order_id=%s: %s",
                handle.seq_id, handle.qmt_order_id, exc,
            )

    def _transition_to_terminal(self, handle: OrderHandle) -> None:
        # Defensive reconciliation per design §21.3: do a final
        # query_stock_trades sweep deduped by trade_id, in case a trade
        # callback was dropped or arrived after we expected. Best effort.
        self._reconcile_fills_from_broker(handle)

        if handle.filled_volume >= handle.submitted_volume:
            handle.state = OrderState.TERMINAL_FILLED
        elif handle.last_status == 57:
            handle.state = OrderState.TERMINAL_REJECTED
        else:
            handle.state = OrderState.TERMINAL_CANCELED

        # Move to archive, drop from active maps.
        self._terminal_archive[handle.seq_id] = handle
        self._handles_by_seq.pop(handle.seq_id, None)
        if handle.qmt_order_id is not None:
            self._terminal_archive[handle.qmt_order_id] = handle
            self._handles_by_order.pop(handle.qmt_order_id, None)

        self._on_terminal_state(handle)

    def _reconcile_fills_from_broker(self, handle: OrderHandle) -> None:
        """Defensive sweep: query_stock_trades and add any unseen trades.
        Best-effort — failures are logged and ignored. The trade_id dedup
        prevents double-counting when both the callback and the query
        return the same trade."""
        if handle.qmt_order_id is None:
            return
        try:
            trades = self._client.query_stock_trades()
        except Exception as exc:
            logger.debug(
                "Defensive reconcile: query_stock_trades failed for seq=%s: %s",
                handle.seq_id, exc,
            )
            return
        if not trades:
            return
        for t in trades:
            tid = (t.get("order_id") if isinstance(t, dict)
                   else getattr(t, "order_id", None))
            if str(tid) != str(handle.qmt_order_id):
                continue
            trade_id = (t.get("traded_id") if isinstance(t, dict)
                        else getattr(t, "traded_id", getattr(t, "trade_id", None)))
            try:
                trade_id = int(trade_id) if trade_id is not None else None
            except (TypeError, ValueError):
                trade_id = None
            if trade_id is None or trade_id in handle.seen_trade_ids:
                continue
            try:
                price = float(t.get("traded_price") if isinstance(t, dict)
                              else getattr(t, "traded_price", 0))
                vol = int(t.get("traded_volume") if isinstance(t, dict)
                          else getattr(t, "traded_volume", 0))
            except (TypeError, ValueError):
                continue
            if vol <= 0:
                continue
            handle.seen_trade_ids.add(trade_id)
            prev_v = handle.filled_volume
            prev_p = handle.filled_avg_price
            new_v = prev_v + vol
            handle.filled_avg_price = (prev_v * prev_p + vol * price) / max(1, new_v)
            handle.filled_volume = new_v
            logger.info(
                "Reconcile: recovered trade_id=%s vol=%d price=%.2f for seq=%s "
                "(callback miss); now filled=%d/%d",
                trade_id, vol, price, handle.seq_id,
                handle.filled_volume, handle.submitted_volume,
            )

    # ---- Terminal-state policy --------------------------------------------

    def _on_terminal_state(self, handle: OrderHandle) -> None:
        remaining = handle.submitted_volume - handle.filled_volume

        # Health accounting
        if handle.state == OrderState.TERMINAL_FILLED:
            self._health.terminal_filled += 1
            self._health.consecutive_abandoned = 0
        elif handle.state == OrderState.TERMINAL_REJECTED:
            self._health.terminal_rejected += 1
            self._health.consecutive_abandoned = 0

        if handle.state == OrderState.TERMINAL_FILLED:
            self._notify(self._callbacks.on_filled, handle)
            self._maybe_fire_next_split_chunk(handle)
            self._check_circuit()
            self._maybe_resolve_chain(handle)
            return

        if handle.state == OrderState.TERMINAL_REJECTED:
            self._notify(self._callbacks.on_rejected, handle)
            self._maybe_fire_next_split_chunk(handle)
            self._check_circuit()
            self._maybe_resolve_chain(handle)
            return

        # Partial accumulator notify (caller updates pending_exit_intent.remaining_size)
        if handle.filled_volume > 0:
            self._notify(self._callbacks.on_partial, handle)

        # SPLIT-SEQUENCE BRANCH: if this handle is part of an active split
        # sequence, the splitter's "fire next chunk with rolled remainder"
        # IS the recovery mechanism — chunk-level resubmit retry would
        # double-up on the same logical fill plan. Per design §21.11,
        # sub-orders are not retried at the chunk level; the splitter
        # owns continuation.
        chain_root = handle.original_handle_id or handle.seq_id
        if chain_root in self._split_sequences:
            # Don't resubmit; let splitter decide. _maybe_fire_next_split_chunk
            # will fire next chunk with rolled remainder OR abort the
            # sequence (per the abort semantics).
            self._maybe_fire_next_split_chunk(handle)
            self._check_circuit()
            self._maybe_resolve_chain(handle)
            return

        max_attempts = MAX_ATTEMPTS_BY_CLASS.get(handle.recovery_class, 3)
        if handle.attempt >= max_attempts:
            self._mark_abandoned(handle, remaining, reason="max_attempts")
            self._maybe_resolve_chain(handle)
            return

        # Resolve next attempt's price; check slippage cap pinned to intended.
        next_attempt = handle.attempt + 1
        try:
            new_price_type, new_price = self._client.resolve_aggressive_price(
                handle.symbol, handle.intent, attempt=next_attempt,
            )
        except Exception as exc:
            logger.error(
                "resolve_aggressive_price failed for resubmit seq=%s: %s",
                handle.seq_id, exc,
            )
            self._mark_abandoned(handle, remaining, reason="price_resolve_failed")
            self._maybe_resolve_chain(handle)
            return

        if new_price > 0 and handle.intended_price > 0:
            slip = abs(new_price - handle.intended_price) / handle.intended_price
            cap = MAX_SLIPPAGE_PCT_BY_CLASS.get(handle.recovery_class, 0.02)
            if slip > cap:
                logger.warning(
                    "Slippage cap exceeded for seq=%s: |%.2f - %.2f|/%.2f = %.4f > %.4f",
                    handle.seq_id, new_price, handle.intended_price,
                    handle.intended_price, slip, cap,
                )
                self._mark_abandoned(handle, remaining, reason="slippage_cap")
                self._maybe_resolve_chain(handle)
                return

        # Build resubmit
        seq_id = self._client.submit_order_async(
            symbol=handle.symbol,
            volume=remaining,
            price=new_price,
            order_type="MARKET",
            intent=handle.intent,
            strategy_name=self._strategy_name,
        )
        if not seq_id:
            self._mark_abandoned(handle, remaining, reason="resubmit_failed")
            self._maybe_resolve_chain(handle)
            return

        new_handle = OrderHandle(
            seq_id=seq_id,
            slot_id=handle.slot_id,
            symbol=handle.symbol,
            intent=handle.intent,
            recovery_class=handle.recovery_class,
            intended_price=handle.intended_price,           # Amendment E pin
            submitted_volume=remaining,
            submitted_price=float(new_price) if new_price > 0 else 0.0,
            submitted_at=datetime.now(),
            attempt=next_attempt,
            original_handle_id=handle.original_handle_id or handle.seq_id,
            state=OrderState.SUBMITTED,
            deadline_at=datetime.now() + timedelta(seconds=self._deadline_s),
            chain_resolved=handle.chain_resolved,           # inherit chain event
        )
        self._handles_by_seq[seq_id] = new_handle
        self._health.submitted += 1
        logger.info(
            "Order RESUBMITTED seq=%d (orig=%s) %s %s vol=%d price=%.2f attempt=%d",
            seq_id, new_handle.original_handle_id, handle.intent, handle.symbol,
            remaining, new_price, next_attempt,
        )

    def _mark_abandoned(self, handle: OrderHandle, remaining: int, reason: str) -> None:
        handle.state = OrderState.TERMINAL_ABANDONED
        handle.abandoned_reason = reason
        if handle.filled_volume > 0:
            self._health.terminal_partial += 1
        else:
            self._health.terminal_abandoned += 1
        self._health.consecutive_abandoned += 1
        logger.error(
            "Order ABANDONED seq=%s slot=%s intent=%s remaining=%d reason=%s",
            handle.seq_id, handle.slot_id, handle.intent, remaining, reason,
        )
        self._notify(self._callbacks.on_abandoned, handle, remaining, reason)
        self._maybe_fire_next_split_chunk(handle)
        self._check_circuit()

    # ---- Circuit breaker --------------------------------------------------

    def _check_circuit(self) -> None:
        if self._tripped:
            return
        h = self._health
        total_terminal = (
            h.terminal_filled + h.terminal_abandoned
            + h.terminal_rejected + h.terminal_partial
        )

        if h.consecutive_abandoned >= CIRCUIT_THRESHOLDS["consecutive_abandoned"]:
            self._trip("consecutive_abandoned")
            return
        if total_terminal >= CIRCUIT_THRESHOLDS["abandoned_rate_min_n"]:
            ab_rate = (h.terminal_abandoned + h.terminal_partial) / total_terminal
            if ab_rate >= CIRCUIT_THRESHOLDS["abandoned_rate_pct"]:
                self._trip("abandoned_rate")
                return
            if h.submitted > 0:
                rj_rate = h.terminal_rejected / h.submitted
                if rj_rate >= CIRCUIT_THRESHOLDS["rejected_rate_pct"]:
                    self._trip("rejected_rate")
                    return
        if h.quiescence_late_trade_count >= CIRCUIT_THRESHOLDS["late_trade_count"]:
            self._trip("late_trade_rate")

    def _trip(self, reason: str) -> None:
        self._tripped = True
        self._tripped_reason = reason
        self._tripped_at = datetime.now()
        logger.critical(
            "OrderRouter CIRCUIT TRIPPED: reason=%s submitted=%d filled=%d "
            "abandoned=%d rejected=%d partial=%d late_trades=%d",
            reason, self._health.submitted, self._health.terminal_filled,
            self._health.terminal_abandoned, self._health.terminal_rejected,
            self._health.terminal_partial, self._health.quiescence_late_trade_count,
        )
        self._persist_circuit_state()
        self._notify(self._callbacks.on_circuit_tripped, reason)

    # ---- Reset-flag-file polling ------------------------------------------

    def _maybe_check_reset_flag(self) -> None:
        if self._state_dir is None:
            return
        now = datetime.now()
        if (now - self._last_reset_check_at).total_seconds() < 1.0:
            return
        self._last_reset_check_at = now
        flag = self._state_dir / "order_router_reset.flag"
        if flag.exists():
            self.reset_circuit(reason="flag_file")
            try:
                flag.unlink()
            except OSError as exc:
                logger.warning("Could not remove reset flag: %s", exc)

    # ---- Persistence ------------------------------------------------------

    def _persist_circuit_state(self) -> None:
        if self._state_dir is None:
            return
        path = self._state_dir / "order_router_state.json"
        payload = {
            "tripped": self._tripped,
            "reason": self._tripped_reason,
            "tripped_at": self._tripped_at.isoformat() if self._tripped_at else None,
        }
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to persist circuit state: %s", exc)

    def _load_persisted_state(self) -> None:
        if self._state_dir is None:
            return
        path = self._state_dir / "order_router_state.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("tripped"):
                self._tripped = True
                self._tripped_reason = data.get("reason", "persisted")
                ts = data.get("tripped_at")
                if ts:
                    self._tripped_at = datetime.fromisoformat(ts)
                logger.warning(
                    "OrderRouter started TRIPPED from persisted state: %s",
                    self._tripped_reason,
                )
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load persisted circuit state: %s", exc)

    # ---- Chain resolution -------------------------------------------------

    def _maybe_resolve_chain(self, handle: OrderHandle) -> None:
        """If no further handles will be created for this chain, signal
        ``handle.chain_resolved``. Idempotent.

        A chain is resolved when:
        - No active handle in _handles_by_seq has the same chain root.
        - No SplitSequence still has remaining chunks for this chain.
        """
        if handle.chain_resolved is None or handle.chain_resolved.is_set():
            return
        chain_root = handle.original_handle_id or handle.seq_id

        for hh in self._handles_by_seq.values():
            root = hh.original_handle_id or hh.seq_id
            if root == chain_root:
                return  # still has an active handle in the chain

        seq = self._split_sequences.get(chain_root)
        if seq is not None and seq.chunks:
            return

        handle.chain_resolved.set()

    # ---- Layer 4 splitter -------------------------------------------------

    def _maybe_split(self, intent: str, symbol: str, volume: int) -> List[int]:
        """Return the chunk plan. ``[volume]`` if no split.

        Splits into chunks <= max(visible_top1 // 2, 1) when the requested
        volume exceeds visible top-of-book. The "//2 conservative" rule
        avoids trying to fully consume the visible quote.
        """
        if volume <= 1:
            return [volume]
        try:
            tick = self._client._get_tick_snapshot(symbol)
        except Exception:
            return [volume]
        if tick is None:
            return [volume]
        is_buy = intent in BUY_INTENTS
        vols = tick.get("askVolume" if is_buy else "bidVolume", []) or []
        try:
            top1 = int(vols[0]) if vols else 0
        except (TypeError, ValueError):
            top1 = 0
        if top1 >= volume:
            return [volume]
        chunk_size = max(1, top1 // 2) if top1 > 0 else 1
        chunks: List[int] = []
        remaining = volume
        while remaining > 0:
            c = min(remaining, chunk_size)
            chunks.append(c)
            remaining -= c
        return chunks

    def _maybe_fire_next_split_chunk(self, handle: OrderHandle) -> None:
        """Called from _on_terminal_state to fire next chunk if in a split
        sequence. Per design §21.11:
        - TERMINAL_FILLED → fire next chunk immediately
        - TERMINAL_CANCELED with >= MIN_PARTIAL_FILL_FRACTION → fire next
          chunk with N's unfilled remainder ROLLED into chunks[0]
        - TERMINAL_CANCELED with < threshold → abort sequence
        - TERMINAL_ABANDONED → abort sequence (regardless of fill fraction)
        - TERMINAL_REJECTED → abort sequence
        """
        # Trace back to parent (the first fired sub-order).
        parent_id = handle.original_handle_id or handle.seq_id
        seq = self._split_sequences.get(parent_id)
        if seq is None:
            return

        seq.total_filled += handle.filled_volume

        # ABANDONED / REJECTED always abort, regardless of partial fill.
        if handle.state in (OrderState.TERMINAL_ABANDONED, OrderState.TERMINAL_REJECTED):
            seq.abandoned = True
            del self._split_sequences[parent_id]
            return

        # No more chunks queued — sequence done.
        if not seq.chunks:
            del self._split_sequences[parent_id]
            return

        # Determine whether to fire next chunk + roll-over remainder.
        unfilled = handle.submitted_volume - handle.filled_volume
        if handle.state == OrderState.TERMINAL_FILLED:
            roll_remainder = 0
        elif handle.state == OrderState.TERMINAL_CANCELED:
            if (handle.submitted_volume > 0 and handle.filled_volume / handle.submitted_volume
                    >= MIN_PARTIAL_FILL_FRACTION):
                roll_remainder = unfilled
            else:
                # Below partial-fill threshold — abort sequence.
                seq.abandoned = True
                del self._split_sequences[parent_id]
                return
        else:
            # Defensive — unknown terminal state, abort.
            seq.abandoned = True
            del self._split_sequences[parent_id]
            return

        # Fire next chunk, with rolled-over remainder added to next chunk's size.
        next_size = seq.chunks.pop(0) + roll_remainder
        try:
            _, price = self._client.resolve_aggressive_price(
                seq.symbol, seq.intent, attempt=1,
            )
        except Exception as exc:
            logger.error("Splitter resolve_price failed for %s: %s", seq.symbol, exc)
            seq.abandoned = True
            del self._split_sequences[parent_id]
            return

        next_seq_id = self._client.submit_order_async(
            symbol=seq.symbol, volume=next_size, price=price,
            order_type="MARKET", intent=seq.intent,
            strategy_name=self._strategy_name,
        )
        if not next_seq_id:
            seq.abandoned = True
            del self._split_sequences[parent_id]
            return

        next_handle = OrderHandle(
            seq_id=next_seq_id, slot_id=seq.slot_id, symbol=seq.symbol,
            intent=seq.intent, recovery_class=RECOVERY_CLASS.get(seq.intent, "ENTRY"),
            intended_price=seq.intended_price,
            submitted_volume=next_size,
            submitted_price=float(price) if price > 0 else 0.0,
            submitted_at=datetime.now(),
            attempt=1,
            original_handle_id=parent_id,
            state=OrderState.SUBMITTED,
            deadline_at=datetime.now() + timedelta(seconds=self._deadline_s),
            chain_resolved=handle.chain_resolved,           # inherit chain event
        )
        self._handles_by_seq[next_seq_id] = next_handle
        seq.fired_handle_ids.append(next_seq_id)
        self._health.submitted += 1
        logger.info(
            "SPLIT NEXT: parent=%d new_seq=%d size=%d remaining_chunks=%s",
            parent_id, next_seq_id, next_size, seq.chunks,
        )

    # ---- Helpers ----------------------------------------------------------

    def _notify(self, cb: Optional[Callable], *args: Any) -> None:
        if cb is None:
            return
        try:
            cb(*args)
        except Exception as exc:
            logger.error("Runner callback raised: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Instrument metadata cache (used by BandGuard + kill_at_band_edge_price)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _InstrumentMeta:
    price_tick: float
    settlement: float
    band_pct: float


_GLOBAL_META_CACHE: Dict[str, _InstrumentMeta] = {}
_GLOBAL_META_CACHE_AT: Optional[datetime] = None
_GLOBAL_META_TTL = timedelta(hours=1)
_GLOBAL_META_LOCK = threading.Lock()


def get_instrument_meta(symbol: str) -> _InstrumentMeta:
    """Look up tick + settlement + band for a contract.

    Cached for ``_GLOBAL_META_TTL`` (1 hour). Settlement doesn't change
    intra-day so an hourly refresh is safe and saves repeated
    ``xtdata.get_instrument_detail`` calls during a cycle.

    Thread-safe via ``_GLOBAL_META_LOCK``. Module-level (not
    OrderRouter-scoped) because BandGuard, the kill-at-band-edge
    formula, and external diagnostics all need it.
    """
    global _GLOBAL_META_CACHE_AT
    with _GLOBAL_META_LOCK:
        now = datetime.now()
        if _GLOBAL_META_CACHE_AT is None or (now - _GLOBAL_META_CACHE_AT) > _GLOBAL_META_TTL:
            _GLOBAL_META_CACHE.clear()
            _GLOBAL_META_CACHE_AT = now
        cached = _GLOBAL_META_CACHE.get(symbol)
        if cached is not None:
            return cached
        try:
            raw = xtdata.get_instrument_detail(symbol)
            detail = raw if isinstance(raw, dict) else {}
            price_tick = float(detail.get("PriceTick", 5.0) or 5.0)
            settlement = float(detail.get("PreSettlementPrice", 0.0) or 0.0)
        except (TypeError, ValueError, Exception):
            price_tick, settlement = 5.0, 0.0
        meta = _InstrumentMeta(
            price_tick=price_tick,
            settlement=settlement,
            band_pct=band_pct_for(symbol),
        )
        _GLOBAL_META_CACHE[symbol] = meta
        return meta


def reset_instrument_meta_cache() -> None:
    """Force-clear the cache (used by tests; rarely useful at runtime)."""
    global _GLOBAL_META_CACHE_AT
    with _GLOBAL_META_LOCK:
        _GLOBAL_META_CACHE.clear()
        _GLOBAL_META_CACHE_AT = None


def kill_at_band_edge_price(symbol: str, intent: str, client: Any = None) -> float:
    """Compute a maximally aggressive limit at fraction × band edge.

    Used by ABANDONED-EXIT recovery (Amendment B) to maximize fill
    probability while staying within the exchange-acceptance band.

    Per design §21.9 fallback: if settlement is unavailable, use
    last_price ± 50 * price_tick instead of raising. The 50-tick
    cushion is roughly equivalent to a 1% offset on most contracts,
    far enough to be marketable but inside any reasonable daily band.
    """
    meta = get_instrument_meta(symbol)
    is_sell = intent in {"EXIT_LONG", "ROLLOVER_CLOSE", "FORCED_EXIT"}
    is_buy = intent == "EXIT_SHORT"
    if not is_sell and not is_buy:
        raise OrderRouterError(f"kill_at_band_edge: unsupported intent {intent}")

    if meta.settlement > 0:
        band_offset = meta.settlement * meta.band_pct * KILL_BAND_FRACTION
        return meta.settlement - band_offset if is_sell else meta.settlement + band_offset

    # Settlement unavailable — fall back to last_price ± 50 ticks.
    if client is None:
        raise OrderRouterError(
            f"kill_at_band_edge: no settlement for {symbol} and no client for fallback"
        )
    try:
        tick = client._get_tick_snapshot(symbol)
    except Exception as exc:
        raise OrderRouterError(
            f"kill_at_band_edge: tick snapshot failed for {symbol}: {exc}"
        )
    last = float(tick.get("lastPrice", 0)) if isinstance(tick, dict) else 0.0
    if last <= 0:
        raise OrderRouterError(
            f"kill_at_band_edge: no settlement, no last_price for {symbol}"
        )
    fallback_offset = 50 * meta.price_tick
    return last - fallback_offset if is_sell else last + fallback_offset


def is_within_band(symbol: str, intent: str, price: float) -> Tuple[bool, str]:
    """Layer 5 BandGuard check. Returns (ok, reason)."""
    meta = get_instrument_meta(symbol)
    if meta.settlement <= 0:
        return True, "settlement_unknown_skipping_check"
    upper = meta.settlement * (1 + meta.band_pct) * (1 - DAILY_BAND_SAFETY_MARGIN)
    lower = meta.settlement * (1 - meta.band_pct) * (1 + DAILY_BAND_SAFETY_MARGIN)
    is_buy = intent in BUY_INTENTS
    if is_buy and price > upper:
        return False, f"buy_{price:.2f}_exceeds_upper_{upper:.2f}"
    if not is_buy and price < lower:
        return False, f"sell_{price:.2f}_below_lower_{lower:.2f}"
    return True, ""
