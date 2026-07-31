"""
Portfolio Risk Overlay
======================

Portfolio-level risk management and position reconciliation.

Responsibilities:
- Portfolio-wide drawdown circuit breaker
- Level 1 reconciliation: verify today's trades vs processed fills
- Level 2 reconciliation: sum(VP) vs QMT NET positions
- Reconciliation logging to CSV
"""

import csv
import json
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .trading_slot import TradingSlot
    from ..platforms.miniqmt.order_router import OrderRouter
    from ..platforms.miniqmt.qmt_client import MiniQMTClient


class PortfolioRiskOverlay:
    """
    Portfolio-level risk checks and reconciliation.

    Operates across all non-errored trading slots.
    """

    def __init__(
        self,
        max_portfolio_drawdown_pct: float = 20.0,
        deploy_data_dir: str = "deploy_data",
    ):
        self._max_dd_pct = max_portfolio_drawdown_pct
        self._deploy_data_dir = deploy_data_dir
        self._peak_portfolio_equity: float = 0.0
        self._peak_slot_equities: Dict[str, float] = {}
        self._recon_log_path = os.path.join(deploy_data_dir, "reconciliation_log.csv")

    @property
    def peak_equity(self) -> float:
        """Public accessor for the rolling peak portfolio equity.

        Internal updates still go through ``_peak_portfolio_equity``;
        external readers (e.g. dashboard generation) should use this
        property to avoid reaching into a leading-underscore attribute.
        """
        return self._peak_portfolio_equity

    # =========================================================================
    # Portfolio drawdown circuit breaker
    # =========================================================================

    def check_portfolio_drawdown(
        self, slots: List['TradingSlot']
    ) -> bool:
        """
        Check portfolio-wide drawdown across ALL slots (including errored).

        Errored slots still hold real capital and positions — excluding
        them would artificially reduce total equity and trigger false
        drawdown breaches.

        Returns True if drawdown is within limits, False if breached.
        """
        active_slots = [s for s in slots if s.capital_slot is not None]
        if not active_slots:
            logger.warning("No slots with capital data — skipping drawdown check")
            return True

        total_equity = sum(s.capital_slot.equity for s in active_slots)

        if total_equity > self._peak_portfolio_equity:
            self._peak_portfolio_equity = total_equity
            self._peak_slot_equities = {
                s.slot_id: s.capital_slot.equity for s in active_slots
            }

        if self._peak_portfolio_equity <= 0:
            return True

        dd_pct = (
            (total_equity - self._peak_portfolio_equity)
            / self._peak_portfolio_equity
            * 100.0
        )

        if dd_pct < -self._max_dd_pct:
            logger.error(
                f"PORTFOLIO DRAWDOWN BREACHED: {dd_pct:.2f}% "
                f"(limit: -{self._max_dd_pct:.1f}%) | "
                f"equity={total_equity:.2f}, peak={self._peak_portfolio_equity:.2f}"
            )
            return False

        logger.info(
            f"Portfolio risk OK: DD={dd_pct:.2f}%, "
            f"equity={total_equity:.2f}, peak={self._peak_portfolio_equity:.2f}"
        )
        return True

    def enforce_portfolio_drawdown(
        self,
        slots: List['TradingSlot'],
        order_router: Optional['OrderRouter'],
    ) -> bool:
        """Check drawdown and trip the OrderRouter circuit on breach.

        Returns True when the portfolio is within limits. On breach, the
        router's persisted circuit state is tripped so restart cannot resume
        order submission until an operator resets the circuit after review.
        """
        ok = self.check_portfolio_drawdown(slots)
        if ok:
            return True

        if order_router is None:
            logger.critical(
                "PORTFOLIO DRAWDOWN BREACHED but no OrderRouter exists to trip"
            )
            return False

        order_router.trip_circuit("portfolio_drawdown")
        return False

    # =========================================================================
    # Level 1: Verify today's trades
    # =========================================================================

    def verify_todays_trades(
        self,
        client: 'MiniQMTClient',
        slots: List['TradingSlot'],
        strategy_name: str = "",
    ) -> Dict[str, Any]:
        """
        Level 1 reconciliation: query_stock_trades vs todays_processed_fills.

        Skips errored slots. Retries once after 1s if mismatch detected,
        because QMT trade history may lag the fill callback by up to ~500ms.
        """
        results = self._l1_query(client, slots)

        # Retry once for any mismatches — QMT trade history lags callbacks
        has_mismatch = any(
            r.get("status") == "mismatch" for r in results.values()
        )
        if has_mismatch:
            import time
            logger.info("L1 mismatch detected — retrying after 1s for QMT trade lag")
            time.sleep(1.0)
            results = self._l1_query(client, slots)

        self._log_reconciliation("L1", results)
        return results

    def _l1_query(
        self,
        client: 'MiniQMTClient',
        slots: List['TradingSlot'],
    ) -> Dict[str, Any]:
        """Single L1 query pass."""
        results: Dict[str, Any] = {}

        for slot in slots:
            if slot.is_errored:
                continue

            slot_id = slot.slot_config.slot_id
            # Only count actual fills (skip canceled/rejected entries)
            processed_count = len([
                f for f in slot.todays_processed_fills
                if not str(f.get('intent', '')).startswith('CANCELED')
            ])

            qmt_trade_count = 0
            try:
                trades = client.query_stock_trades()
                if trades:
                    cycle_order_ids = {
                        str(f.get('qmt_order_id', ''))
                        for f in slot.todays_processed_fills
                        if not str(f.get('intent', '')).startswith('CANCELED')
                    }
                    slot_trades = [
                        t for t in trades
                        if str(t.get('order_id', '')) in cycle_order_ids
                    ]
                    qmt_trade_count = len(slot_trades)
            except Exception as e:
                logger.warning(f"[{slot_id}] L1 recon: failed to query trades: {e}")
                results[slot_id] = {"status": "error", "error": str(e)}
                continue

            match = processed_count == qmt_trade_count
            results[slot_id] = {
                "status": "match" if match else "mismatch",
                "processed": processed_count,
                "qmt": qmt_trade_count,
            }

            if not match:
                logger.warning(
                    f"[{slot_id}] L1 MISMATCH: processed={processed_count}, "
                    f"qmt={qmt_trade_count}"
                )

        return results

    # =========================================================================
    # Level 2: Cross-check aggregate positions
    # =========================================================================

    def cross_check_aggregate(
        self,
        client: 'MiniQMTClient',
        slots: List['TradingSlot'],
    ) -> Dict[str, Any]:
        """
        Level 2 reconciliation: sum(VP sizes) vs QMT NET positions per contract.

        Includes errored slots — they still hold real positions at the
        exchange level even if their strategy code failed.
        """
        # Aggregate VP sizes by contract
        # Normalize contract keys: strip exchange suffix (e.g. ".SF")
        # to match QMT's position keys (e.g. "cu2604" not "cu2604.SF")
        vp_by_contract: Dict[str, float] = {}
        for slot in slots:
            contract = slot.trading_contract or ""
            if not contract:
                continue
            # Strip exchange suffix for comparison with QMT keys
            contract_bare = contract.split(".")[0] if "." in contract else contract
            portfolio = slot.portfolio
            if portfolio is None:
                continue
            signed_size = portfolio.get_position_size()
            vp_by_contract[contract_bare] = vp_by_contract.get(contract_bare, 0) + signed_size

        # Query QMT positions
        qmt_by_contract: Dict[str, float] = {}
        try:
            positions = client.get_positions()
            for pos_info in positions.values():
                symbol = pos_info.symbol
                size = float(pos_info.volume)
                if pos_info.direction == "SHORT":
                    size = -size
                qmt_by_contract[symbol] = qmt_by_contract.get(symbol, 0) + size
        except Exception as e:
            logger.warning(f"L2 recon: failed to query positions: {e}")
            return {"status": "error", "error": str(e)}

        # Compare
        all_contracts = set(vp_by_contract.keys()) | set(qmt_by_contract.keys())
        results: Dict[str, Any] = {}

        for contract in all_contracts:
            vp_size = vp_by_contract.get(contract, 0)
            qmt_size = qmt_by_contract.get(contract, 0)
            match = abs(vp_size - qmt_size) < 0.01

            results[contract] = {
                "status": "match" if match else "mismatch",
                "vp": vp_size,
                "qmt": qmt_size,
            }

            if not match:
                logger.warning(
                    f"L2 MISMATCH [{contract}]: VP={vp_size}, QMT={qmt_size}"
                )

        self._log_reconciliation("L2", results)
        return results

    # =========================================================================
    # Persistence
    # =========================================================================

    def save(self, path: Optional[str] = None) -> None:
        """Save risk overlay state."""
        save_path = path or os.path.join(self._deploy_data_dir, "risk_overlay_state.json")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump({
                'peak_portfolio_equity': self._peak_portfolio_equity,
                'peak_slot_equities': self._peak_slot_equities,
                'max_portfolio_drawdown_pct': self._max_dd_pct,
            }, f, indent=2)

    def load(
        self,
        active_slot_ids: Optional[List[str]] = None,
        path: Optional[str] = None,
    ) -> None:
        """
        Load risk overlay state.

        If active_slot_ids is provided and the stored peak was recorded
        with a different slot composition, the peak is adjusted by summing
        only the still-active slots' equity contributions at peak time.
        This prevents phantom drawdown breaches when slots are enabled/disabled.
        """
        load_path = path or os.path.join(self._deploy_data_dir, "risk_overlay_state.json")
        if not os.path.exists(load_path):
            return

        with open(load_path, 'r') as f:
            data = json.load(f)

        stored_peak = data.get('peak_portfolio_equity', 0.0)
        stored_slot_equities = data.get('peak_slot_equities', {})

        if active_slot_ids is not None:
            current_ids = set(active_slot_ids)
            stored_ids = set(stored_slot_equities.keys())

            if stored_slot_equities and current_ids != stored_ids:
                # Per-slot breakdown available — recompute peak from surviving slots
                adjusted_peak = sum(
                    eq for sid, eq in stored_slot_equities.items()
                    if sid in current_ids
                )
                logger.warning(
                    f"Slot composition changed ({sorted(stored_ids)} → "
                    f"{sorted(current_ids)}): peak adjusted from "
                    f"{stored_peak:.2f} to {adjusted_peak:.2f}"
                )
                self._peak_portfolio_equity = adjusted_peak
                self._peak_slot_equities = {
                    sid: eq for sid, eq in stored_slot_equities.items()
                    if sid in current_ids
                }
                return

            if not stored_slot_equities and stored_peak > 0:
                # No per-slot breakdown (migration or empty snapshot) — cannot
                # determine which slots contributed to the stored peak.
                # Reset to 0; next check_portfolio_drawdown will set peak to
                # current equity of active slots.
                logger.warning(
                    f"No peak_slot_equities in state (stored peak="
                    f"{stored_peak:.2f}). Resetting peak to 0 for "
                    f"active slots {sorted(current_ids)}."
                )
                self._peak_portfolio_equity = 0.0
                self._peak_slot_equities = {}
                return

        self._peak_portfolio_equity = stored_peak
        self._peak_slot_equities = stored_slot_equities

    # =========================================================================
    # Reconciliation log
    # =========================================================================

    def _log_reconciliation(self, level: str, results: Dict[str, Any]) -> None:
        """Append reconciliation results to CSV log."""
        os.makedirs(os.path.dirname(self._recon_log_path), exist_ok=True)

        file_exists = os.path.exists(self._recon_log_path)
        with open(self._recon_log_path, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['timestamp', 'level', 'key', 'status', 'details'])
            timestamp = datetime.now().isoformat()
            for key, detail in results.items():
                status = detail.get('status', 'unknown') if isinstance(detail, dict) else str(detail)
                writer.writerow([timestamp, level, key, status, json.dumps(detail)])
