"""One-cycle coordinator for the bundle-era live book path.

LIVE PARITY RULE (S3): the live view is produced by the SAME ``PanelData``
class from a snapshot directory in the SAME on-disk format the research
pipeline writes. There is no separate live PanelView implementation; any
divergence between research and live panel semantics is a bug by definition.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Protocol

from echolon.panel import PanelData, PanelView
from echolon.portfolio import BookState, RebalanceRecord, TargetBook

from .executor import TargetExecutor
from .models import BookRunResult
from .risk import BookRiskOverlay


class RebalancingStrategy(Protocol):
    """S7 PortfolioStrategy surface used by the runner."""

    def rebalance(self, view: PanelView, book: BookState) -> tuple[TargetBook, RebalanceRecord]: ...


class BookRunner:
    """Risk-check, rebalance, and execute one cycle of the live book."""

    def __init__(
        self,
        *,
        book_id: str,
        strategy: RebalancingStrategy,
        executor: TargetExecutor,
        risk_overlay: BookRiskOverlay,
    ) -> None:
        self.book_id = book_id
        self.strategy = strategy
        self.executor = executor
        self.risk_overlay = risk_overlay

    def run_once(
        self,
        *,
        view: PanelView,
        book: BookState,
        current_lots: Mapping[str, int] | None = None,
    ) -> BookRunResult:
        """One end-of-day cycle: breaker → rebalance → diff → submit.

        ``current_lots`` defaults to the signed lots in ``book.positions``;
        pass it explicitly when the authoritative held positions come from a
        separate store (e.g. broker-reconciled state).
        """
        risk = self.risk_overlay.check(book)
        if risk.halt:
            return BookRunResult(
                halted=True, risk=risk, target=None, orders=[], rebalance_record=None
            )
        target, record = self.strategy.rebalance(view, book)
        if current_lots is None:
            current_lots = {
                instrument: position.lots for instrument, position in book.positions.items()
            }
        orders = self.executor.execute(target, current_lots=current_lots)
        return BookRunResult(
            halted=False, risk=risk, target=target, orders=orders, rebalance_record=record
        )


def load_live_panel_view(snapshot_dir, date: dt.date) -> PanelView:
    """Load today's live view through the exact immutable PanelData contract.

    ``PanelData.load`` verifies the snapshot manifest hashes (S4) before any
    bar is readable, so a corrupted live snapshot refuses to load rather than
    silently feeding the strategy.
    """
    return PanelData.load(snapshot_dir).view(date)
