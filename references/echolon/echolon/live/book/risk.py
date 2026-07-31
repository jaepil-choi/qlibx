"""Book-level binding risk overlay + broker reconciliation.

The drawdown breaker is BINDING: the bundle ships a capital-relative
``max_drawdown_pct_of_equity``; the private platform instantiates it in RMB
for the allocated equity and passes the RMB number here. On breach the
overlay trips the shared OrderRouter circuit (persisted by the router), so
a restart cannot resume order submission until an operator resets it.

Halt semantics: flatten-allowed / no-new-orders. The overlay blocks new
rebalance orders via the halt result and the router circuit; the operator
flatten path is expected to reset the circuit explicitly (an operator
action), submit EXIT-class orders, and re-trip.

L1/L2 reconciliation is ported from ``live/slot/risk_overlay.py`` for the
single-book world:
- L1: today's processed fills vs the broker's trade query (count match,
  with one retry because QMT trade history can lag callbacks ~500ms).
- L2: book positions per contract vs the broker's NET positions.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from echolon.portfolio import BookState

from .models import OrderRouterLike, QMTClientLike, RiskCheckResult

logger = logging.getLogger(__name__)


class BookRiskOverlay:
    """Binding book breaker: trips the order-router circuit on breach."""

    def __init__(
        self,
        *,
        max_drawdown_rmb: float,
        router: OrderRouterLike,
        state_path: Path | str | None = None,
    ) -> None:
        if max_drawdown_rmb <= 0:
            raise ValueError("max_drawdown_rmb must be positive")
        self.max_drawdown_rmb = float(max_drawdown_rmb)
        self.router = router
        self.state_path = Path(state_path) if state_path is not None else None
        self.peak_equity_rmb: float | None = None
        self._load_state()

    def check(self, book: BookState) -> RiskCheckResult:
        """Update the equity peak and halt if the RMB drawdown limit is hit."""
        equity = float(book.equity_rmb)
        if self.peak_equity_rmb is None or equity > self.peak_equity_rmb:
            self.peak_equity_rmb = equity
            self._save_state()
        drawdown_rmb = self.peak_equity_rmb - equity
        metrics = {
            "equity_rmb": equity,
            "peak_equity_rmb": self.peak_equity_rmb,
            "drawdown_rmb": drawdown_rmb,
            "max_drawdown_rmb": self.max_drawdown_rmb,
        }
        if drawdown_rmb >= self.max_drawdown_rmb:
            reason = "book_drawdown"
            self.router.trip_circuit(
                f"{reason}: {drawdown_rmb:.2f} RMB >= {self.max_drawdown_rmb:.2f} RMB "
                f"(equity {equity:.2f}, peak {self.peak_equity_rmb:.2f})"
            )
            return RiskCheckResult(halt=True, reason=reason, metrics=metrics)
        return RiskCheckResult(halt=False, metrics=metrics)

    def external_halt(self, reason: str) -> RiskCheckResult:
        """Halt on an externally supplied trigger (e.g. a divergence BREACH).

        This is the GoingMerry-side S10 hook: the divergence engine itself
        lives in navika; the platform only needs a way to convert a BREACH
        verdict into the same binding halt the drawdown breaker uses.
        """
        if not reason:
            raise ValueError("external_halt requires a non-empty reason")
        self.router.trip_circuit(reason)
        return RiskCheckResult(halt=True, reason=reason, metrics={})

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        peak = data.get("peak_equity_rmb")
        self.peak_equity_rmb = float(peak) if peak is not None else None

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"peak_equity_rmb": self.peak_equity_rmb}, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.state_path)


class BookReconciler:
    """L1/L2 reconciliation between the book's records and the broker."""

    def __init__(
        self,
        *,
        log_path: Path | str | None = None,
        retry_sleep_s: float = 1.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path is not None else None
        self.retry_sleep_s = float(retry_sleep_s)
        if sleep is None:
            import time

            sleep = time.sleep
        self._sleep = sleep

    # ---- L1: today's fills vs broker trade history --------------------------

    def verify_todays_trades(
        self,
        client: QMTClientLike,
        todays_fills: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Compare processed fill count vs broker trades for those order ids.

        Retries once after ``retry_sleep_s`` on mismatch because QMT trade
        history may lag the fill callback by up to ~500ms.
        """
        result = self._l1_query(client, todays_fills)
        if result.get("status") == "mismatch":
            logger.info("L1 mismatch detected — retrying after %.1fs for QMT trade lag", self.retry_sleep_s)
            self._sleep(self.retry_sleep_s)
            result = self._l1_query(client, todays_fills)
        self._log("L1", {"book": result})
        return result

    def _l1_query(
        self,
        client: QMTClientLike,
        todays_fills: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        processed = [
            fill
            for fill in todays_fills
            if not str(fill.get("intent", "")).startswith("CANCELED")
        ]
        order_ids = {str(fill.get("qmt_order_id", "")) for fill in processed}
        try:
            trades = client.query_stock_trades() or []
        except Exception as exc:  # broker query failure is reported, not hidden
            logger.warning("L1 recon: failed to query trades: %s", exc)
            return {"status": "error", "error": str(exc)}
        matched = [
            trade
            for trade in trades
            if str(_field(trade, "order_id", "")) in order_ids
        ]
        match = len(processed) == len(matched)
        if not match:
            logger.warning(
                "L1 MISMATCH: processed=%d, qmt=%d", len(processed), len(matched)
            )
        return {
            "status": "match" if match else "mismatch",
            "processed": len(processed),
            "qmt": len(matched),
        }

    # ---- L2: book positions vs broker NET positions -------------------------

    def cross_check_positions(
        self,
        client: QMTClientLike,
        book_lots_by_contract: Mapping[str, float],
    ) -> dict[str, Any]:
        """Compare the book's signed lots per contract vs broker positions.

        Contract keys are compared bare (exchange suffix stripped) to match
        QMT's position keys (e.g. "cu2608" not "cu2608.SF").
        """
        book: dict[str, float] = {}
        for contract, lots in book_lots_by_contract.items():
            bare = contract.split(".")[0]
            book[bare] = book.get(bare, 0.0) + float(lots)

        broker: dict[str, float] = {}
        try:
            positions = client.get_positions() or {}
        except Exception as exc:
            logger.warning("L2 recon: failed to query positions: %s", exc)
            return {"status": "error", "error": str(exc)}
        for pos in positions.values():
            symbol = str(_field(pos, "symbol", "")).split(".")[0]
            size = float(_field(pos, "volume", 0))
            if str(_field(pos, "direction", "LONG")) == "SHORT":
                size = -size
            broker[symbol] = broker.get(symbol, 0.0) + size

        results: dict[str, Any] = {}
        for contract in sorted(set(book) | set(broker)):
            book_size = book.get(contract, 0.0)
            broker_size = broker.get(contract, 0.0)
            match = abs(book_size - broker_size) < 0.01
            results[contract] = {
                "status": "match" if match else "mismatch",
                "book": book_size,
                "qmt": broker_size,
            }
            if not match:
                logger.warning(
                    "L2 MISMATCH [%s]: book=%s, qmt=%s", contract, book_size, broker_size
                )
        self._log("L2", results)
        return results

    # ---- persistence ---------------------------------------------------------

    def _log(self, level: str, results: Mapping[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = self.log_path.exists()
        with self.log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if not file_exists:
                writer.writerow(["timestamp", "level", "key", "status", "details"])
            timestamp = datetime.now().isoformat()
            for key, detail in results.items():
                status = detail.get("status", "unknown") if isinstance(detail, dict) else str(detail)
                writer.writerow([timestamp, level, key, status, json.dumps(detail)])


def _field(record: Any, name: str, default: Any) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)
