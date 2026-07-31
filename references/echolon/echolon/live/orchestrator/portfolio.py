"""
Portfolio Trading Runner
========================

Main orchestrator for multi-instrument, multi-strategy parallel trading.

Long-running process that:
- Connects one MiniQMTClient (shared across all slots)
- Schedules daily trading jobs via APScheduler
- Runs per-slot initialize → execute → order fire → fill process → reconcile
- Persists state atomically per slot

Phases per daily cycle:
0. Group slots by (instrument, bar_size), run data pipeline + indicator union
1. Per-slot initialize (failure isolation)
2. Per-slot execute_bar (skip errored)
2.5. Central order firing (deferred execution burst)
3. Process fills (wait callbacks, update VP, log)
3.5. Reconciliation (Level 1 + 2)
4. Portfolio risk check
5. Dashboard
6. Health report + reschedule
"""

import json
import os
import re
import signal
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytz

from ..config.deploy_config import QMTAccountConfig
from ..config.portfolio_deploy_config import PortfolioDeployConfig, SlotConfig
from ..config.logging_config import get_deploy_logger, init_logging, shutdown_logging
try:
    from ..platforms.miniqmt.qmt_client import MiniQMTClient
    from ..platforms.miniqmt.order_router import (
        OrderRouter, RouterCallbacks, OrderHandle, OrderState,
    )
except ImportError:
    MiniQMTClient = None
    OrderRouter = None
    RouterCallbacks = None
    OrderHandle = None
    OrderState = None

from ..config.qmt_constants import QMT_STATUS_MAP

from echolon.data.loaders.contract_loader import get_main_contract
from echolon.strategy.interfaces import Order, OrderIntent, OrderStatus
from ..slot.capital_slot import CapitalSlot
from ..slot.trading_slot import TradingSlot
from ..slot.risk_overlay import PortfolioRiskOverlay
from echolon.data.loaders.calendar_loader import is_night_market_open
import logging

logger = logging.getLogger(__name__)


def _numeric_attr(obj: Any, names: tuple[str, ...]) -> Optional[float]:
    for name in names:
        value = getattr(obj, name, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _instrument_code_for_fill(slot: "TradingSlot", order: "Order") -> str:
    slot_code = getattr(slot.slot_config, "instrument_code", None)
    if slot_code:
        return str(slot_code).lower()
    match = re.match(r"([A-Za-z]+)", order.symbol or "")
    if match:
        return match.group(1).lower()
    raise ValueError(f"Cannot resolve instrument code for fill symbol={order.symbol!r}")


def _resolve_execution_commission(
    *,
    slot: "TradingSlot",
    order: "Order",
    handle: Any,
    traded_price: float,
    traded_volume: int,
) -> tuple[float, str]:
    broker_commission = _numeric_attr(
        handle,
        (
            "commission",
            "filled_commission",
            "broker_commission",
            "traded_commission",
        ),
    )
    if broker_commission is not None:
        return broker_commission, "broker"

    from echolon.config.markets.shfe.instruments import get_instrument

    instrument_code = _instrument_code_for_fill(slot, order)
    spec = get_instrument(instrument_code)
    return (
        spec.calculate_commission(price=traded_price, size=traded_volume),
        "computed",
    )


def book_terminal_record(
    *,
    slot: "TradingSlot",
    order: "Order",
    handle: Any,
    kind: str,
    reason: str,
    slots_dir: str,
    log: Any,
    resolve_fill_price: Optional[Callable[[int, str], float]] = None,
) -> None:
    """Book a single terminal record for one (slot, order) pair.

    Replaces the three near-identical 80-line branches that lived in
    PortfolioTradingRunner._process_fills (status 56=FILLED, 53/54=CANCELED/
    ABANDONED, 57=REJECTED). Behavior is bit-for-bit equivalent to the
    pre-refactor inline branches:

    Branch gating (matches original):
        kind == "filled" AND handle.filled_volume > 0   -> FILLED logic
        kind == "filled" AND handle.filled_volume == 0  -> silent return
                                                          (matches original
                                                          fall-through; status
                                                          56 + volume 0 hit
                                                          no elif)
        kind == "rejected"                               -> REJECTED logic
        kind in ("canceled", "abandoned", "partial")    -> CANCELED logic

    Inner exception boundary (matches original):
        FILLED branch's VP update + dict appends + notify_fill +
        save_trade_execution are wrapped in a try/except that logs
        ``[slot_id] VP update/logging failed: <exc>``.

    PRICE_UNKNOWN guard:
        Inside the FILLED branch, if traded_price <= 0 after resolve attempt,
        appends a fill record with ``error='PRICE_UNKNOWN'`` and returns
        WITHOUT mutating VP.
    """
    from ..io.data_logger import save_trade_execution
    from ..config.qmt_constants import QMT_STATUS_MAP

    sc = slot.slot_config
    trade_data_dir = os.path.join(slots_dir, slot.slot_id)
    real_id = handle.qmt_order_id or handle.seq_id
    intent_str = order.intent.value if order.intent else ""

    # FILLED branch — matches original `if status == 56 and traded_volume > 0`.
    # When kind=="filled" with volume==0, fall through to silent return.
    if kind == "filled":
        traded_price = handle.filled_avg_price
        traded_volume = handle.filled_volume
        if traded_volume <= 0:
            return  # silent fall-through; matches pre-refactor behavior

        # PRICE_UNKNOWN guard
        if traded_price <= 0 and resolve_fill_price is not None:
            traded_price = resolve_fill_price(real_id, slot.slot_id)
        if traded_price <= 0:
            log.error(
                f"[{slot.slot_id}] CRITICAL: Fill price unresolvable for "
                f"order_id={real_id}. Skipping VP update to prevent "
                f"capital corruption. Manual reconciliation required."
            )
            slot.todays_processed_fills.append({
                'qmt_order_id': real_id,
                'slot_id': slot.slot_id,
                'intent': intent_str,
                'price': 0.0,
                'volume': traded_volume,
                'timestamp': datetime.now().isoformat(),
                'error': 'PRICE_UNKNOWN',
            })
            return

        # P1.1 guard: a None intent on a FILLED record is a bug in the
        # caller (Order should always have an intent). The pre-refactor
        # code silently no-op'd VP and recorded a phantom fill — that
        # masked the upstream bug. Refuse to book and log loudly.
        if order.intent is None:
            log.error(
                f"[{slot.slot_id}] Refusing to book FILLED record with no "
                f"intent (order_id={real_id}, volume={traded_volume}). "
                f"This indicates a caller bug — investigate."
            )
            return

        # Inner try/except wraps order-state mutation + VP update + dict
        # appends + strategy_logger + notify_fill + save_trade_execution.
        # If any step fails, order.status stays at PENDING (callers using
        # status to infer VP consistency are not misled).
        try:
            prev_pos = slot.portfolio.get_position()
            prev_size = int(prev_pos.size) if prev_pos else 0
            prev_avg = prev_pos.avg_price if prev_pos else 0.0
            prev_realized = slot.capital_slot.realized_pnl

            # Apply fill to VP (intent -> portfolio mutation; replaces
            # the now-deleted _apply_fill_to_vp method).
            portfolio = slot.portfolio
            intent = order.intent
            if intent in (OrderIntent.ENTRY_LONG, OrderIntent.ROLLOVER_OPEN):
                portfolio.open_position(symbol=order.symbol, direction="LONG",
                                        size=traded_volume, price=traded_price)
            elif intent == OrderIntent.ENTRY_SHORT:
                portfolio.open_position(symbol=order.symbol, direction="SHORT",
                                        size=traded_volume, price=traded_price)
            elif intent in (OrderIntent.EXIT_LONG, OrderIntent.EXIT_SHORT,
                            OrderIntent.FORCED_EXIT, OrderIntent.ROLLOVER_CLOSE):
                portfolio.close_position(size=traded_volume, price=traded_price)

            # Status/filled fields mutated only AFTER the VP mutation
            # succeeded. If VP raised, status stays at PENDING — callers
            # using status to infer VP consistency are not misled.
            order.status = OrderStatus.FILLED
            order.filled_price = traded_price
            order.filled_size = traded_volume

            cur_pos = slot.portfolio.get_position()
            cur_size = int(cur_pos.size) if cur_pos else 0
            cur_avg = cur_pos.avg_price if cur_pos else 0.0
            trade_realized_pnl = slot.capital_slot.realized_pnl - prev_realized
            commission, commission_source = _resolve_execution_commission(
                slot=slot,
                order=order,
                handle=handle,
                traded_price=traded_price,
                traded_volume=traded_volume,
            )

            slot.todays_processed_fills.append({
                'qmt_order_id': real_id,
                'slot_id': slot.slot_id,
                'intent': intent_str,
                'price': traded_price,
                'volume': traded_volume,
                'commission': commission,
                'commission_source': commission_source,
                'timestamp': datetime.now().isoformat(),
            })

            if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                slot.strategy.strategy_logger.log_order_event({
                    'action': 'executed',
                    'ref': order.metadata.get('internal_ref', ''),
                    'execution_price': traded_price,
                    'executed_size': traded_volume,
                    'execution_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })
            if slot.strategy:
                slot.strategy.total_trades = getattr(slot.strategy, 'total_trades', 0) + 1

            # Top-level state update
            if intent in (OrderIntent.ENTRY_LONG, OrderIntent.ROLLOVER_OPEN):
                fill_side = "LONG"
            elif intent == OrderIntent.ENTRY_SHORT:
                fill_side = "SHORT"
            else:
                fill_side = "FLAT"
            slot.notify_fill(
                symbol=order.symbol, side=fill_side,
                size=traded_volume, price=traded_price,
                bar_count=getattr(slot.strategy, 'bar_count', 0),
            )

            save_trade_execution(
                trading_data_dir=trade_data_dir,
                order_info={
                    'order_id': str(real_id),
                    'direction': intent_str,
                    'order_type': 'MARKET',
                    'submitted_price': order.price or 0.0,
                    'submitted_size': int(order.size) if order.size else 0,
                },
                execution_details={
                    'executed_price': traded_price,
                    'executed_size': traded_volume,
                    'commission': commission,
                    'commission_source': commission_source,
                    'status': QMT_STATUS_MAP[56],
                },
                position_impact={
                    'position_before': prev_size,
                    'position_after': cur_size,
                    'avg_price_before': prev_avg,
                    'avg_price_after': cur_avg,
                },
                pnl_impact={
                    'realized_pnl': trade_realized_pnl,
                    'unrealized_pnl': slot.portfolio.get_unrealized_pnl(),
                },
                symbol=sc.instrument,
            )
        except Exception as e:
            log.error(f"[{slot.slot_id}] VP update/logging failed: {e}")
        return

    # REJECTED branch — matches original status==57.
    # NB: rejected branch does NOT append to todays_processed_fills.
    if kind == "rejected":
        msg = handle.last_status_msg or reason
        log.error(f"[{slot.slot_id}] Order rejected: order_id={real_id}, msg={msg}")
        try:
            order.status = OrderStatus.REJECTED

            if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                slot.strategy.strategy_logger.log_order_event({
                    'action': 'rejected',
                    'status': 'Rejected',
                    'ref': order.metadata.get('internal_ref', ''),
                })

            save_trade_execution(
                trading_data_dir=trade_data_dir,
                order_info={
                    'order_id': str(real_id),
                    'direction': intent_str,
                    'order_type': 'MARKET',
                    'submitted_price': order.price or 0.0,
                    'submitted_size': int(order.size) if order.size else 0,
                },
                execution_details={
                    'executed_price': 0.0,
                    'executed_size': 0,
                    'commission': 0.0,
                    'status': 'REJECTED',
                },
                position_impact={
                    'position_before': 0,
                    'position_after': 0,
                    'avg_price_before': 0.0,
                    'avg_price_after': 0.0,
                },
                pnl_impact={'realized_pnl': 0.0, 'unrealized_pnl': 0.0},
                symbol=sc.instrument,
            )
        except Exception as e:
            log.error(f"[{slot.slot_id}] Rejected-bookkeeping failed: {e}")
        return

    # CANCELED / ABANDONED branch — matches original status in (53, 54).
    msg = handle.last_status_msg or reason
    log.warning(f"[{slot.slot_id}] Order canceled: order_id={real_id}, msg={msg}")
    try:
        order.status = OrderStatus.CANCELLED

        if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
            slot.strategy.strategy_logger.log_order_event({
                'action': 'cancelled',
                'status': 'Cancelled',
                'ref': order.metadata.get('internal_ref', ''),
            })

        slot.todays_processed_fills.append({
            'qmt_order_id': real_id,
            'slot_id': slot.slot_id,
            'intent': f"CANCELED_{intent_str}" if intent_str else 'CANCELED',
            'price': 0.0,
            'volume': 0,
            'timestamp': datetime.now().isoformat(),
        })

        save_trade_execution(
            trading_data_dir=trade_data_dir,
            order_info={
                'order_id': str(real_id),
                'direction': intent_str,
                'order_type': 'MARKET',
                'submitted_price': order.price or 0.0,
                'submitted_size': int(order.size) if order.size else 0,
            },
            execution_details={
                'executed_price': 0.0,
                'executed_size': 0,
                'commission': 0.0,
                'status': 'CANCELED',
            },
            position_impact={
                'position_before': 0,
                'position_after': 0,
                'avg_price_before': 0.0,
                'avg_price_after': 0.0,
            },
            pnl_impact={'realized_pnl': 0.0, 'unrealized_pnl': 0.0},
            symbol=sc.instrument,
        )
    except Exception as e:
        log.error(f"[{slot.slot_id}] Canceled-bookkeeping failed: {e}")


class PortfolioTradingRunner:
    """
    Multi-slot trading orchestrator.

    Manages N TradingSlots on one shared QMT connection.
    """

    TIMEZONE = pytz.timezone("Asia/Shanghai")

    # Default base directory for all deploy runtime data
    DEFAULT_DEPLOY_DIR = os.path.join("workspace", "deploy")

    def __init__(self, config: PortfolioDeployConfig, deploy_data_dir: str = None):
        self.config = config
        self.deploy_data_dir = deploy_data_dir or self.DEFAULT_DEPLOY_DIR

        # Structured subdirectories
        self.slots_dir = os.path.join(self.deploy_data_dir, "slots")
        self.portfolio_dir = os.path.join(self.deploy_data_dir, "portfolio")
        self.logs_dir = os.path.join(self.deploy_data_dir, "logs")

        # Shared QMT client
        self.client: Optional[MiniQMTClient] = None
        # OrderRouter — drives all order lifecycle (Phase 2+).
        self.order_router: Optional["OrderRouter"] = None

        # Slots — each gets workspace/deploy/slots/{slot_id}/
        self.slots: List[TradingSlot] = []
        for sc in config.get_enabled_slots():
            self.slots.append(TradingSlot(slot_config=sc, deploy_data_dir=self.slots_dir))

        # Risk overlay — writes to workspace/deploy/portfolio/
        self.risk_overlay = PortfolioRiskOverlay(
            max_portfolio_drawdown_pct=config.deploy.max_portfolio_drawdown_pct,
            deploy_data_dir=self.portfolio_dir,
        )

        # Cached market_data_dir for calendar_loader calls (is_night_market_open
        # takes it as a kw-only arg; DailyScheduler also receives it).
        from echolon.config.paths_config import PathsConfig
        self._market_data_dir = PathsConfig.from_env().market_data_dir

        # Scheduling — DailyScheduler owns the BackgroundScheduler instance.
        self.scheduler: Optional["DailyScheduler"] = None
        self.running = False
        self.shutdown_event = threading.Event()
        self.present_date = datetime.now()

        # OrderRouter-driven state. Replaces the legacy _order_events /
        # _seq_to_order_id / _unmapped_callbacks plumbing. All order
        # lifecycle is now owned by OrderRouter; the runner observes via
        # RouterCallbacks and queues bookkeeping records here for the
        # main thread to drain in _process_fills.
        self._callback_lock = threading.Lock()
        # Per-slot list of (Order, OrderHandle) — handle holds the chain.
        self._slot_handle_map: Dict[str, List[Tuple[Order, "OrderHandle"]]] = {}
        # Terminal-event records produced by router callbacks (watchdog
        # thread); _process_fills drains and books these on the main
        # thread to avoid concurrent VP mutations.
        self._slot_terminal_records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        # Logging
        init_logging(self.logs_dir)
        self.log = get_deploy_logger("portfolio_runner")

    # =========================================================================
    # Public API
    # =========================================================================

    def run(self) -> None:
        """Main entry: connect, schedule, block until shutdown."""
        self.log.info("=" * 70)
        self.log.info("STARTING PORTFOLIO TRADING RUNNER")
        self.log.info(f"Slots: {[s.slot_id for s in self.slots]}")
        active = self.config.get_active_account()
        self.log.info(
            f"Account: {active.account_id} "
            f"({'TEST' if self.config.account.use_test_account else 'LIVE'})"
        )
        self.log.info("=" * 70)

        self.running = True

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        # Windows-only — NSSM's stop sequence escalates from Ctrl+C
        # (SIGINT) to Ctrl+Break (SIGBREAK) after a 1.5s grace period.
        # Without this handler the second event would terminate the
        # process abruptly, skipping our cleanup.
        original_sigbreak = None
        if hasattr(signal, "SIGBREAK"):
            original_sigbreak = signal.getsignal(signal.SIGBREAK)
            signal.signal(signal.SIGBREAK, self._signal_handler)

        try:
            # Disable Windows CMD QuickEdit Mode — accidental clicks must
            # not pause the trader by blocking stdout. No-op on non-Windows.
            from echolon._internal.console_utils import disable_quickedit_mode
            disable_quickedit_mode()

            self._connect_client()
            self.risk_overlay.load(active_slot_ids=[s.slot_id for s in self.slots])

            from .scheduler import DailyScheduler
            self.scheduler = DailyScheduler(
                config=self.config,
                slots=[s.slot_config for s in self.slots],
                market_data_dir=self._market_data_dir,
                portfolio_dir=self.portfolio_dir,
                timezone=self.TIMEZONE,
                log=self.log,
            )
            self.scheduler.start(
                on_cycle_trigger=self._market_open_job_inner,
                on_present_date_set=lambda dt: setattr(self, "present_date", dt),
                is_running=lambda: self.running,
                slot_count=lambda: len(self.slots),
                order_router_tripped=lambda: (
                    self.order_router.is_tripped if self.order_router else None
                ),
            )

            while self.running and not self.shutdown_event.is_set():
                self.shutdown_event.wait(timeout=60)
                # Heartbeat: write a timestamp file every minute so the
                # operator can verify liveness via `type scheduler_heartbeat.txt`
                # without depending on console output (which can block).
                if self.scheduler:
                    self.scheduler.write_heartbeat()
        except Exception as e:
            self.log.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            if original_sigbreak is not None:
                signal.signal(signal.SIGBREAK, original_sigbreak)
            self.stop()

    def run_single_cycle(self) -> Dict[str, Any]:
        """Execute a single trading cycle for testing."""
        self.log.info("Running single portfolio cycle (test mode)")
        self.running = True
        try:
            self._connect_client()
            self._ensure_trading_calendars()  # thin shim -> scheduler module
            self.risk_overlay.load(active_slot_ids=[s.slot_id for s in self.slots])
            return self._market_open_job_inner()
        except Exception as e:
            self.log.error(f"Single cycle failed: {e}\n{traceback.format_exc()}")
            return {"status": "error", "error": str(e)}
        finally:
            self.running = False

    def stop(self) -> None:
        """Graceful shutdown."""
        if not self.running and self.shutdown_event.is_set():
            return

        self.log.info("Initiating graceful shutdown...")
        self.running = False
        self.shutdown_event.set()

        # Finalize per-slot strategy loggers
        for slot in self.slots:
            if slot.strategy and hasattr(slot.strategy, 'strategy_logger'):
                try:
                    sl = slot.strategy.strategy_logger
                    if sl:
                        sl.finalize_logging()
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] Logger finalize error: {e}")

        if self.order_router:
            try:
                self.order_router.shutdown()
            except Exception:
                pass
            self.order_router = None

        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

        if self.scheduler:
            try:
                self.scheduler.shutdown()
            except Exception:
                pass
            self.scheduler = None

        self.risk_overlay.save()
        shutdown_logging()

    # =========================================================================
    # Connection
    # =========================================================================

    def _connect_client(self) -> None:
        """Create and connect shared MiniQMTClient + OrderRouter."""
        account_cfg = self.config.get_active_account()
        # Use first slot's instrument for the MiniQMTClient init
        first_slot = self.slots[0].slot_config if self.slots else None
        market = first_slot.market if first_slot else "SHFE"
        asset = first_slot.instrument if first_slot else "aluminum"

        self.client = MiniQMTClient(
            config=account_cfg,
            market=market,
            asset=asset,
        )
        connected = self.client.connect()
        if connected:
            self.log.info("QMT connection established")
            # Construct OrderRouter — it registers its own callbacks on
            # the client. The router fans out to our handlers below.
            callbacks = RouterCallbacks(
                on_filled=self._on_router_filled,
                on_partial=self._on_router_partial,
                on_abandoned=self._on_router_abandoned,
                on_rejected=self._on_router_rejected,
                on_circuit_tripped=self._on_router_circuit_tripped,
            )
            self.order_router = OrderRouter(
                client=self.client,
                callbacks=callbacks,
                state_dir=Path(self.portfolio_dir),
            )
            self.order_router.start()
            self.log.info("OrderRouter started")
            if self.order_router.is_tripped:
                self.log.critical(
                    f"OrderRouter started TRIPPED from persisted state: "
                    f"{self.order_router.tripped_reason}. Run "
                    f"`goingmerry order-router-reset` after investigating."
                )
        else:
            self.log.warning("QMT connection failed (may be outside trading hours)")

    # =========================================================================
    # Daily cycle (the scheduling itself lives in scheduler.DailyScheduler;
    # the runner contributes the cycle body invoked via callback)
    # =========================================================================

    def _market_open_job_inner(self) -> Dict[str, Any]:
        """Core daily cycle logic."""
        cycle_start = datetime.now()
        results: Dict[str, Any] = {"status": "success", "timestamp": cycle_start.isoformat()}

        # Clear stale state
        self._slot_handle_map.clear()
        self._slot_terminal_records.clear()
        # Reset OrderRouter per-cycle health metrics so that
        # abandon/reject rates aren't diluted by all-time totals.
        if self.order_router is not None:
            self.order_router.reset_cycle_metrics()
        for slot in self.slots:
            slot.reset_daily_state()

        # Phase 0: Data pipeline per (instrument, bar_size) group
        self._phase0_data_pipeline()

        # Phase 1: Per-slot initialize (failure isolation)
        calendar_path = self._get_calendar_path()
        for slot in self.slots:
            try:
                slot.initialize(self.present_date, calendar_path=calendar_path)
                # Set client on engine
                if self.client:
                    slot.engine.set_client(self.client)
            except Exception as e:
                slot.mark_error(f"Init failed: {e}")
                self.log.error(f"[{slot.slot_id}] Init failed:\n{traceback.format_exc()}")

        # Phase 2: Per-slot execute_bar
        for slot in self.slots:
            if slot.is_errored:
                continue
            try:
                slot.execute_bar()
                self.log.info(f"[{slot.slot_id}] execute_bar complete")
                # Surface the strategy's decision (entry/exit reason) so the
                # operator can understand WHY an order was queued before it
                # is actually fired during the night-market open.  Goes to
                # both terminal and qts_system.log via the runner logger.
                self._log_strategy_decision(slot)
            except Exception as e:
                slot.mark_error(f"execute_bar failed: {e}")
                self.log.error(f"[{slot.slot_id}] execute_bar failed:\n{traceback.format_exc()}")

        # Phase 2.5: Central order firing
        self._execute_pending_orders()

        # Phase 3: Process fills
        self._process_fills()

        # Phase 3.5: Reconciliation
        if self.client:
            try:
                self.risk_overlay.verify_todays_trades(self.client, self.slots)
                self.risk_overlay.cross_check_aggregate(self.client, self.slots)
            except Exception as e:
                self.log.error(f"Reconciliation failed: {e}")

        # Phase 4: Portfolio risk check
        dd_ok = self.risk_overlay.enforce_portfolio_drawdown(
            self.slots,
            order_router=self.order_router,
        )
        if not dd_ok:
            self.log.critical(
                "PORTFOLIO DRAWDOWN LIMIT BREACHED — trading cycle halted; "
                "OrderRouter circuit tripped"
            )
            results["drawdown_breached"] = True
            results["status"] = "halted"
            self.running = False
            self.shutdown_event.set()
            self.risk_overlay.save()
            duration = (datetime.now() - cycle_start).total_seconds()
            results["duration_seconds"] = duration
            self._save_health_report(cycle_start, results)
            return results

        # Phase 5: Save trading data snapshot + state + health report
        from ..io.data_logger import save_trading_data_snapshot
        for slot in self.slots:
            if not slot.is_errored:
                # Save daily trading data snapshot (equity curve source)
                try:
                    snap = slot.build_snapshot_data()
                    sc = slot.slot_config
                    trade_data_dir = os.path.join(self.slots_dir, sc.slot_id)
                    save_trading_data_snapshot(
                        trading_data_dir=trade_data_dir,
                        **snap,
                    )
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] Trading data snapshot failed: {e}")

                try:
                    slot.save_state()
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] State save failed: {e}")

            # Finalize strategy logger
            if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                try:
                    slot.strategy.strategy_logger.finalize_logging()
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] Logger finalize failed: {e}")

        self.risk_overlay.save()

        # Phase 6: Dashboard (after data save so files exist)
        try:
            self._generate_dashboard()
        except Exception as e:
            self.log.error(f"Dashboard generation failed: {e}")

        self._save_health_report(cycle_start, results)

        duration = (datetime.now() - cycle_start).total_seconds()
        results["duration_seconds"] = duration
        self.log.info(f"Portfolio cycle completed in {duration:.1f}s")

        from echolon._internal.atomic_state import update_heartbeat
        update_heartbeat(
            workspace_deploy_dir=self.deploy_data_dir,
            slots_alive=[s.slot_id for s in self.slots],
        )

        return results

    # =========================================================================
    # Decision logging
    # =========================================================================

    def _log_strategy_decision(self, slot: TradingSlot) -> None:
        """Log the strategy's per-bar entry/exit decision via the runner logger.

        Reads from the strategy's CSVStrategyLogger ``current_bar_data`` so the
        same fields that land in ``qmt_<instrument>.csv`` (entry_signal,
        entry_reason, exit_should_exit, exit_reason, risk reasons, etc.) are
        also surfaced in ``qts_system.log`` and the terminal at execute_bar
        time — i.e. before the night market opens and orders are fired.

        Defensive against missing logger / missing fields: this is best-effort
        diagnostic output and must never raise.
        """
        try:
            strategy = getattr(slot, 'strategy', None)
            slogger = getattr(strategy, 'strategy_logger', None) if strategy else None
            bar = getattr(slogger, 'current_bar_data', None) if slogger else None
            if not bar:
                return

            entry_signal = bar.get('entry_signal', 'HOLD')
            entry_reason = bar.get('entry_reason', '')
            should_exit = bar.get('exit_should_exit', False)
            exit_reason = bar.get('exit_reason', '')
            risk_allowed = bar.get('risk_trading_allowed', '')
            risk_reason = bar.get('risk_reason', '')
            position = bar.get('capital_position_size', 0.0)

            self.log.info(
                f"[{slot.slot_id}] DECISION: position={position} "
                f"risk_allowed={risk_allowed} | "
                f"entry={entry_signal} | exit_triggered={should_exit}"
            )
            if exit_reason:
                self.log.info(f"[{slot.slot_id}]   exit_reason: {exit_reason}")
            if entry_reason:
                self.log.info(f"[{slot.slot_id}]   entry_reason: {entry_reason}")
            if risk_reason:
                self.log.info(f"[{slot.slot_id}]   risk_reason: {risk_reason}")
        except Exception as e:
            # Never let decision-logging break the cycle.
            self.log.warning(f"[{slot.slot_id}] _log_strategy_decision failed: {e}")

    # =========================================================================
    # Phase 0: Data pipeline
    # =========================================================================

    def _phase0_data_pipeline(self) -> None:
        """Run data pipeline per instrument, then indicators per slot.

        Implementation in echolon.live.orchestrator.phase0_pipeline.
        Raises RuntimeError if XtdcClient is unavailable — caller (the
        cycle) propagates and the cycle aborts.
        """
        from .phase0_pipeline import Phase0DataPipeline
        Phase0DataPipeline(config=self.config, log=self.log).run(self.present_date)

    # =========================================================================
    # Phase 2.5: Central order firing
    # =========================================================================

    def _execute_pending_orders(self) -> None:
        """
        Collect all pending orders from non-errored slots, fire via QMT.

        Uses order_stock_async for burst-fire, then maps qmt_order_ids back.
        """
        if self.client is None:
            self.log.warning("No client — orders will not be executed")
            return

        all_pending: List[Tuple[TradingSlot, Order]] = []
        for slot in self.slots:
            if slot.is_errored:
                continue
            for order in slot.get_pending_orders():
                all_pending.append((slot, order))

        if not all_pending:
            self.log.info("No pending orders to execute")
            return

        # Per-slot pending order detail — makes the source of each queued
        # order unambiguous in qts_system.log.  Without this, "Firing N
        # orders" alone does not identify which slots produced them.
        self.log.info(f"Pending orders breakdown ({len(all_pending)} total):")
        for slot, order in all_pending:
            intent_str = order.intent.value if order.intent else "UNKNOWN"
            price_str = f"{order.price}" if order.price is not None else "MARKET"
            self.log.info(
                f"  [{slot.slot_id}] {intent_str} size={int(order.size)} "
                f"price={price_str} contract={order.symbol}"
            )

        self.log.info(f"Firing {len(all_pending)} orders")

        # Subscribe tick data for all pending order symbols BEFORE the
        # central wait. By the time night market opens (21:00), the tick
        # cache will have ~18 minutes of warm data for price resolution.
        subscribed = set()
        for slot, order in all_pending:
            sym = order.symbol
            if sym not in subscribed:
                self.client.subscribe_tick(sym)
                subscribed.add(sym)

        # Central wait for night market open (21:00 CST)
        self._central_wait_if_night_market()

        for slot, order in all_pending:
            slot_id = slot.slot_id
            try:
                intent_str = order.intent.value if order.intent else "ENTRY_LONG"

                # Phase 2: route through OrderRouter. The router runs the
                # state machine, watchdog cancel-and-resubmit, splitter,
                # BandGuard, and circuit breaker. We only see terminal
                # outcomes via the callbacks wired in _connect_client.
                if self.order_router is None:
                    order.status = OrderStatus.REJECTED
                    self.log.error(f"[{slot_id}] No OrderRouter — cannot submit")
                    continue

                # If this is an EXIT-class order, set pending_exit_intent
                # BEFORE the first attempt — Amendment B. This way even
                # an immediate-rejection abandons can be recovered next cycle.
                if intent_str in ("EXIT_LONG", "EXIT_SHORT", "ROLLOVER_CLOSE", "FORCED_EXIT"):
                    self._set_pending_exit_intent(
                        slot=slot, intent=intent_str,
                        original_size=int(order.size),
                    )

                # If the caller specified an explicit price (e.g. the
                # kill-at-band-edge recovery in TradingSlot._resume_pending_exit),
                # honor it as a LIMIT — bypass router's aggressive pricing.
                # Strategies that want MARKET-equivalent behaviour leave
                # order.price=None.
                if order.price is not None and float(order.price) > 0:
                    handle = self.order_router.submit_order(
                        intent=intent_str,
                        symbol=order.symbol,
                        volume=int(order.size),
                        slot_id=slot_id,
                        intended_price=float(order.price),
                        force_price=float(order.price),
                    )
                else:
                    handle = self.order_router.submit_order(
                        intent=intent_str,
                        symbol=order.symbol,
                        volume=int(order.size),
                        slot_id=slot_id,
                        intended_price=order.price,
                    )

                if handle.state == OrderState.SUBMITTED:
                    order.status = OrderStatus.SUBMITTED
                    order.metadata['qmt_seq_id'] = handle.seq_id
                    self._slot_handle_map.setdefault(slot_id, []).append((order, handle))
                    self.log.info(
                        f"[{slot_id}] Routed: {intent_str} "
                        f"{order.size}@{order.price} -> seq={handle.seq_id} "
                        f"submitted_price={handle.submitted_price:.2f}"
                    )
                else:
                    # Immediate rejection (e.g. submit_order_async returned no seq_id).
                    order.status = OrderStatus.REJECTED
                    self.log.error(
                        f"[{slot_id}] OrderRouter rejected immediately: {intent_str} "
                        f"state={handle.state.value} msg={handle.last_status_msg}"
                    )

            except Exception as e:
                order.status = OrderStatus.REJECTED
                self.log.error(f"[{slot_id}] Order fire error: {e}\n{traceback.format_exc()}")

    # =========================================================================
    # Phase 3: Process fills
    # =========================================================================

    def _process_fills(self, timeout: float = 600.0) -> None:
        """Wait for OrderRouter chain resolution per submitted intent,
        then book all terminal events on the main thread.

        Router callbacks fire on the watchdog thread and append to
        self._slot_terminal_records. We block per intent's chain_resolved
        event until the full retry+split chain is done, then drain the
        recorded terminal events for that slot's intents.
        """
        # Phase A — block until every submitted intent's chain has fully resolved.
        for slot_id, order_list in self._slot_handle_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue
            for order, handle in order_list:
                if handle.chain_resolved is None:
                    continue
                self.log.info(
                    f"[{slot_id}] Waiting for chain seq={handle.seq_id} "
                    f"({order.intent.value if order.intent else '?'} "
                    f"{order.size}@{order.price})..."
                )
                resolved = handle.chain_resolved.wait(timeout=timeout)
                if not resolved:
                    self.log.warning(
                        f"[{slot_id}] Chain timeout seq={handle.seq_id} "
                        f"after {timeout}s — booking partial state"
                    )

        # Phase B — book the recorded terminal events on the main thread.
        for slot_id, order_list in self._slot_handle_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue

            with self._callback_lock:
                records = list(self._slot_terminal_records.get(slot_id, []))

            for record in records:
                kind = record["kind"]
                handle = record["handle"]
                chain_root = handle.original_handle_id or handle.seq_id
                order = self._find_order_for_chain(order_list, chain_root)
                if order is None:
                    self.log.debug(
                        f"[{slot_id}] Skipping record kind={kind} "
                        f"seq={handle.seq_id}: no matching order in handle_map"
                    )
                    continue

                # Map kind → status code (matches original if/elif chain).
                if kind == "filled":
                    status_code = 56
                elif kind == "partial":
                    status_code = 55
                elif kind == "rejected":
                    status_code = 57
                else:                       # canceled / abandoned
                    status_code = 54

                exec_status = QMT_STATUS_MAP.get(status_code, f'UNKNOWN_{status_code}')

                self.log.info(
                    f"[{slot_id}] Terminal: kind={kind} "
                    f"status={exec_status} price={handle.filled_avg_price} "
                    f"volume={handle.filled_volume} seq={handle.seq_id} "
                    f"reason={record.get('reason', '')}"
                )

                # Map kind to the helper's branch vocabulary. 'partial' is
                # not currently emitted as a terminal record — if it ever is,
                # treat as filled (helper's filled branch handles partial fills
                # via filled_volume).
                book_kind = "filled" if kind in ("filled", "partial") else (
                    "rejected" if kind == "rejected" else "canceled"
                )

                try:
                    book_terminal_record(
                        slot=slot, order=order, handle=handle,
                        kind=book_kind, reason=record.get("reason", ""),
                        slots_dir=self.slots_dir,
                        log=self.log,
                        resolve_fill_price=self._resolve_fill_price,
                    )
                except Exception as e:
                    self.log.error(f"[{slot_id}] book_terminal_record failed: {e}")

        # Phase C — chain-aware pending_exit_intent reconciliation
        # (Amendment B). Process AFTER per-record bookkeeping so split chains
        # are accounted in aggregate. For each EXIT-class submitted intent,
        # sum filled_volume across the entire chain (parent + retries +
        # split chunks) and decide whether to clear or update the intent.
        for slot_id, order_list in self._slot_handle_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue
            with self._callback_lock:
                records = list(self._slot_terminal_records.get(slot_id, []))
            for order, parent_handle in order_list:
                intent_str = order.intent.value if order.intent else ""
                if intent_str not in (
                    "EXIT_LONG", "EXIT_SHORT", "ROLLOVER_CLOSE", "FORCED_EXIT"
                ):
                    continue
                chain_root = parent_handle.seq_id
                chain_records = [
                    r for r in records
                    if (r["handle"].original_handle_id or r["handle"].seq_id)
                    == chain_root
                ]
                # Sum filled across all chain handles. Each handle's
                # filled_volume is the deduped sum of its trade callbacks.
                # Per-handle filled is independent so summing is safe.
                seen_handles: Dict[int, int] = {}
                for r in chain_records:
                    seen_handles[r["handle"].seq_id] = r["handle"].filled_volume
                total_filled = sum(seen_handles.values())
                original = int(order.size)
                remaining = max(0, original - total_filled)
                if remaining <= 0:
                    self._clear_pending_exit_intent(slot)
                else:
                    self._update_pending_exit_remaining(slot, remaining)

    def _resolve_fill_price(self, order_id: int, slot_id: str) -> float:
        """Attempt to resolve a fill price when the trade callback didn't
        provide one. Fallback queries QMT trade history.
        """
        if self.client:
            try:
                trades = self.client.query_stock_trades()
                if trades:
                    for t in trades:
                        tid = t.get('order_id') if isinstance(t, dict) else getattr(t, 'order_id', None)
                        if str(tid) == str(order_id):
                            price = float(t.get('traded_price', 0) if isinstance(t, dict) else getattr(t, 'traded_price', 0))
                            if price > 0:
                                self.log.info(f"[{slot_id}] Price resolved (QMT query): {price}")
                                return price
            except Exception as e:
                self.log.warning(f"[{slot_id}] QMT trade query failed: {e}")

        self.log.error(f"[{slot_id}] Price resolution FAILED for order_id={order_id}")
        return 0.0

    # =========================================================================
    # OrderRouter callbacks (from watchdog thread — append-only here)
    # =========================================================================

    def _on_router_filled(self, handle: "OrderHandle") -> None:
        """Router-side notification that a handle reached TERMINAL_FILLED."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "filled", "handle": handle,
            })

    def _on_router_partial(self, handle: "OrderHandle") -> None:
        """A handle's chain has accumulated some fill but isn't complete yet."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "partial", "handle": handle,
            })

    def _on_router_abandoned(
        self, handle: "OrderHandle", remaining: int, reason: str,
    ) -> None:
        """Chain exhausted retries / hit slippage cap / etc."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "abandoned", "handle": handle,
                "remaining": remaining, "reason": reason,
            })

    def _on_router_rejected(self, handle: "OrderHandle") -> None:
        """Broker rejected the order."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "rejected", "handle": handle,
            })

    def _on_router_circuit_tripped(self, reason: str) -> None:
        """Circuit broke — log critical alert. The router itself refuses
        further submits via OrderRouterTripped; nothing for us to gate."""
        self.log.critical(
            f"OrderRouter circuit TRIPPED: {reason}. "
            f"Cycle continues to drain in-flight orders. "
            f"Run `goingmerry order-router-reset` after investigating."
        )

    # ---- Pending-exit-intent helpers (Amendment B) ------------------------
    #
    # Slot-side state mutations live on TradingSlot. These runner wrappers
    # preserve the original try/except + self.log error reporting so the
    # log namespace stays `deploy.portfolio_runner` for ops triage.

    def _set_pending_exit_intent(
        self, slot: TradingSlot, intent: str, original_size: int,
    ) -> None:
        try:
            slot.set_pending_exit_intent(intent=intent, original_size=original_size)
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] set_pending_exit_intent failed: {exc}")

    def _clear_pending_exit_intent(self, slot: TradingSlot) -> None:
        try:
            slot.clear_pending_exit_intent()
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] clear_pending_exit_intent failed: {exc}")
        # Also remove operator alert row for this slot, if any. This block
        # runs even if clear_pending_exit_intent above raised — preserves
        # the original two-try-block structure.
        try:
            self._remove_pending_exit_alert(slot.slot_id)
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] remove_pending_exit_alert failed: {exc}")

    def _remove_pending_exit_alert(self, slot_id: str) -> None:
        """Remove a slot's entry from pending_exit_alerts.json."""
        alert_path = Path(self.portfolio_dir) / "pending_exit_alerts.json"
        if not alert_path.exists():
            return
        try:
            with open(alert_path, "r") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                return
        except (OSError, json.JSONDecodeError):
            return
        new = [a for a in existing if a.get("slot_id") != slot_id]
        if len(new) == len(existing):
            return
        tmp = alert_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(new, f, indent=2)
        os.replace(tmp, alert_path)

    def _update_pending_exit_remaining(
        self, slot: TradingSlot, remaining: int,
    ) -> None:
        try:
            slot.update_pending_exit_remaining(remaining=remaining)
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] update_pending_exit_remaining failed: {exc}")

    # ---- Lookup helpers ---------------------------------------------------

    def _find_order_for_chain(
        self,
        order_list: List[Tuple[Order, "OrderHandle"]],
        chain_root_seq: int,
    ) -> Optional[Order]:
        """Locate the originating Order for a handle in a retry/split chain.

        Returns ``None`` when no order in the slot's tracked list matches
        the chain root (e.g. an immediately-rejected handle whose fake
        seq_id never made it into ``_slot_handle_map``). Callers MUST
        handle ``None`` and skip the record — using a wrong order would
        write the rejected status to a different order's CSV and corrupt
        the audit trail.
        """
        for order, parent_handle in order_list:
            if parent_handle.seq_id == chain_root_seq:
                return order
        return None

    # =========================================================================
    # Dashboard
    # =========================================================================

    def _generate_dashboard(self) -> None:
        """Generate per-slot + portfolio aggregate dashboard and save locally."""
        from ..io.kpi_aggregator import generate_portfolio_dashboard, save_portfolio_dashboard

        # Build slot statuses from runtime state
        slot_statuses = {}
        for slot in self.slots:
            if slot.is_errored:
                slot_statuses[slot.slot_id] = 'ERROR'
            else:
                slot_statuses[slot.slot_id] = 'OK'

        # Portfolio equity/peak from runtime
        portfolio_equity = sum(
            s.capital_slot.equity for s in self.slots if s.capital_slot
        )
        portfolio_peak = self.risk_overlay.peak_equity

        dashboard = generate_portfolio_dashboard(
            deploy_config=self.config,
            deploy_data_dir=self.deploy_data_dir,
            portfolio_equity=portfolio_equity,
            portfolio_peak=portfolio_peak,
            slot_statuses=slot_statuses,
        )

        out_path = os.path.join(self.portfolio_dir, "dashboard_portfolio.json")
        save_portfolio_dashboard(dashboard, out_path)

    # =========================================================================
    # Health report
    # =========================================================================

    def _save_health_report(self, cycle_start: datetime, results: Dict[str, Any]) -> None:
        """Save cycle_health_report.json."""
        report = {
            'timestamp': cycle_start.isoformat(),
            'duration_seconds': (datetime.now() - cycle_start).total_seconds(),
            'overall_status': results.get('status', 'unknown'),
            'slots': {},
        }

        has_price_failures = False
        for slot in self.slots:
            # Detect fills with unresolved prices
            price_unknown_fills = [
                f for f in slot.todays_processed_fills
                if f.get('error') == 'PRICE_UNKNOWN'
            ]
            if price_unknown_fills:
                has_price_failures = True

            report['slots'][slot.slot_id] = {
                'is_errored': slot.is_errored,
                'error_message': slot.error_message,
                'fills': len(slot.todays_processed_fills),
                'fills_price_unknown': len(price_unknown_fills),
                'equity': slot.capital_slot.equity if slot.capital_slot else 0,
                'drawdown_pct': slot.capital_slot.drawdown_pct if slot.capital_slot else 0,
            }

        if has_price_failures:
            report['overall_status'] = 'WARNING_PRICE_UNKNOWN'
            report['warning'] = (
                'One or more fills had unresolvable prices. VP was NOT updated '
                'for these fills. Manual reconciliation required — check QMT '
                'positions vs strategy state.'
            )

        path = os.path.join(self.portfolio_dir, "cycle_health_report.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _ensure_trading_calendars(self) -> None:
        """Thin shim onto scheduler.ensure_trading_calendars.

        Kept on the runner so callers without a DailyScheduler instance
        (run_single_cycle and the goingmerry test_slot_init_only.py
        script) can still materialize calendars before is_trading_day()
        lookups.
        """
        from .scheduler import ensure_trading_calendars
        ensure_trading_calendars(
            config=self.config,
            market_data_dir=self._market_data_dir,
            log=self.log,
        )

    def _central_wait_if_night_market(self) -> None:
        """
        If today is a night market day, wait until 21:00 CST before firing orders.

        Uses Asia/Shanghai timezone. Coarse sleep (releases GIL) + spin-wait
        for sub-10ms precision at market open.
        """
        first = self.slots[0].slot_config if self.slots else None
        if not first:
            return

        try:
            is_night = is_night_market_open(
                first.market, first.instrument, self.present_date,
                market_data_dir=self._market_data_dir,
            )
        except Exception:
            is_night = False

        if not is_night:
            # Day-only session — no need to wait
            time.sleep(2)  # Brief settlement wait
            return

        now_shanghai = datetime.now(self.TIMEZONE)
        # Target 1s after session open to avoid the call-auction-to-continuous
        # transition window. Orders in the first ~500ms can be rejected.
        target = now_shanghai.replace(hour=21, minute=0, second=1, microsecond=0)

        # If we're already past 21:00, no wait needed
        if now_shanghai >= target:
            self.log.info("Night market already open, firing immediately")
            return

        remaining = (target - now_shanghai).total_seconds()
        self.log.info(f"Night market wait: {remaining:.0f}s until 21:00 CST")

        # Coarse sleep — releases GIL, immune to C-extension contention
        while True:
            now_shanghai = datetime.now(self.TIMEZONE)
            remaining = (target - now_shanghai).total_seconds()
            if remaining <= 1.0:
                break
            time.sleep(min(remaining - 1.0, 30.0))

        # Spin-wait for sub-10ms precision at market open
        while datetime.now(self.TIMEZONE) < target:
            time.sleep(0.005)

        self.log.info("Night market open — firing orders now")

    def _get_slot_by_id(self, slot_id: str) -> Optional[TradingSlot]:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None

    def _get_calendar_path(self) -> Optional[str]:
        """Get path to the deploy trading calendar.

        The CSV is supplied by the operator via the JSON config
        (``deploy.trading_calendar_path``), not bundled with echolon.
        """
        path = self.config.deploy.trading_calendar_path
        if not path:
            raise FileNotFoundError(
                "deploy.trading_calendar_path is not set in PortfolioDeployConfig; "
                "supply it via the JSON config (e.g. "
                "goingmerry/session/portfolio_deploy_config.json)."
            )
        return path

    def _signal_handler(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM."""
        self.log.info(f"Received signal {signum} — shutting down")
        self.stop()
