"""ACCRUE: the first stage of a market-clock instant, and for now an empty one.

Design §3.1 puts ACCRUE before EXECUTE -- dividends, stock-lending income, perpetual funding,
futures daily settlement, fund subscriptions and redemptions are compensation for a holding
period that has already passed, so they are recognised before this instant's fills change the
book. Design §7.3 fixes the place and the wiring only: everything an accrual decides -- ex-date
or pay-date, withholding, reinvestment -- is an economic choice the framework must not make, so
this handler does nothing until a venue or a run says what it should. The stage is timed and
guarded like every other, so the record already has a column for the cost it will one day have.
"""

from __future__ import annotations

from datetime import datetime

from vqapr.flow.engine.artifacts import SimulationStage
from vqapr.flow.strategy.context import FlowContext


class AccrualHandler:
    """The place ACCRUE will be computed. Wired; empty by owner decision (design §7.3)."""

    def __init__(self, context: FlowContext) -> None:
        self._context = context

    def accrue(self, instant: datetime) -> None:
        """Recognise what the holding period up to `instant` earned. Nothing, for now."""
        with self._context.guard(
            SimulationStage.MARKET_ACCRUE, instant, owner=self._context.frozen_run.execution
        ):
            return None


__all__ = ["AccrualHandler"]
