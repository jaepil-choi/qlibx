"""Generic live book execution primitives for the bundle-era path.

This package is deliberately broker-light: it loads a verified release
bundle into a runnable strategy, converts target lots into OrderRouter
submissions, and enforces book-level halt checks — but it does not own
QMT connection setup, scheduling, capital numbers, or account identity.
GoingMerry remains the private runtime that wires those on the live host.
"""
from .bundle_runtime import BundleStrategyRuntime, load_bundle_strategy
from .executor import TargetExecutor
from .models import (
    BookRunResult,
    DiffOrder,
    OrderRouterLike,
    QMTClientLike,
    RiskCheckResult,
)
from .paper import (
    PaperFill,
    PaperPosition,
    margin_used_rmb,
    simulate_paper_fill,
    unrealized_pnl_rmb,
)
from .risk import BookReconciler, BookRiskOverlay
from .runner import BookRunner, load_live_panel_view

__all__ = [
    "BookReconciler",
    "BookRiskOverlay",
    "BookRunResult",
    "BookRunner",
    "BundleStrategyRuntime",
    "DiffOrder",
    "OrderRouterLike",
    "PaperFill",
    "PaperPosition",
    "QMTClientLike",
    "RiskCheckResult",
    "TargetExecutor",
    "load_bundle_strategy",
    "load_live_panel_view",
    "margin_used_rmb",
    "simulate_paper_fill",
    "unrealized_pnl_rmb",
]
