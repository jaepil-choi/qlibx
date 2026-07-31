"""Echolon live trading — MiniQMT portfolio runner.

================================================================
PUBLIC CONTRACT: `workspace/deploy/slots/` path layout (semver-stable)
================================================================

The on-disk layout `workspace/deploy/slots/{slot_id}/` is part of
echolon's public API as of 2026-05-13 per Q52 (qorka decisions_log.md
"Pre-Wave-1A plan-composition readiness pass"). External tools —
notably qorka's A9 §4.11 live-replay diagnostic — read these paths as
a documented public contract. Renames/restructures of files inside this
tree are semver-breaking changes that require a major version bump in
echolon and prior coordination with consumers.

Per-slot directory layout::

    workspace/deploy/slots/{slot_id}/
    ├── strategy_state.json          # serialized position, daily_pnl,
    │                                # capital, VirtualPosition state
    │                                # (per slot/trading_slot.py)
    ├── trading_data_*.csv           # per-cycle TradingDataRecord rows
    │                                # (per io/data_logger.py)
    ├── trade_executions_*.csv       # per-fill TradeExecution rows
    │                                # (per io/data_logger.py)
    └── ...

Per-portfolio directory layout (aggregated across slots)::

    workspace/deploy/portfolio/
    ├── dashboard_portfolio.json     # portfolio-level KPI aggregate
    │                                # (per io/kpi_aggregator.py
    │                                #  aggregate_portfolio)
    └── ...

**Reader-side public API** for these paths (use these instead of
hard-coding paths in consumer code):

- :func:`load_slot_state` — read a slot's strategy_state.json
- :func:`load_equity_curve` — read a slot's equity curve from
  trading_data_*.csv
- :func:`aggregate_portfolio` — aggregate per-slot states into a
  portfolio dashboard payload

The path-layout commitment is what qorka's A9 cost-calibration and
live-replay diagnostic depend on. Breaking it without coordination
silently breaks A9.

Per `qorka/docs/3_roadmap/echolon_dependencies.md` (2026-05-12 audit).
"""

from echolon.live.io.kpi_aggregator import (
    aggregate_portfolio,
    generate_portfolio_dashboard,
    load_equity_curve,
    load_slot_state,
    save_portfolio_dashboard,
)
from echolon.live.orchestrator.portfolio import PortfolioTradingRunner

# Semver-stable public path layout per Q52. Consumers should use the
# reader functions (aggregate_portfolio / load_slot_state / load_equity_curve)
# rather than hard-coding these paths, but the layout itself is also
# part of the public contract for diagnostic tools.
DEPLOY_SLOTS_DIR_TEMPLATE = "workspace/deploy/slots/{slot_id}"
DEPLOY_PORTFOLIO_DIR = "workspace/deploy/portfolio"

# Per-slot file conventions (Q52 public contract):
SLOT_STATE_FILE = "strategy_state.json"
SLOT_TRADING_DATA_PATTERN = "trading_data_*.csv"
SLOT_TRADE_EXECUTIONS_PATTERN = "trade_executions_*.csv"

# Per-portfolio file conventions (Q52 public contract):
PORTFOLIO_DASHBOARD_FILE = "dashboard_portfolio.json"

__all__ = [
    "PortfolioTradingRunner",
    # Dashboard public API
    "aggregate_portfolio",
    "load_slot_state",
    "load_equity_curve",
    "generate_portfolio_dashboard",
    "save_portfolio_dashboard",
    # Q52 public path-layout contract — semver-stable
    "DEPLOY_SLOTS_DIR_TEMPLATE",
    "DEPLOY_PORTFOLIO_DIR",
    "SLOT_STATE_FILE",
    "SLOT_TRADING_DATA_PATTERN",
    "SLOT_TRADE_EXECUTIONS_PATTERN",
    "PORTFOLIO_DASHBOARD_FILE",
]
