"""
Risk Manager Component - Platform-Agnostic

Implements drawdown-based trading halt for SHFE aluminum futures (interday).
Business logic sourced exclusively from risk_prompt.md.

Risk Controls (from risk_prompt.md — action_type: KEEP):
    - Max drawdown limit: 6.5% from equity peak → HALT all trading
      (range: [6.0, 7.0]; dd_metrics: realized=5.84%, headroom=9.16pp,
       false_activations=0, longest_underwater=475d, time_elevated=47.53%)
    - Regime coverage: ALL six entry pathways (trending_up LONG, volatile SHORT,
      ranging LONG, ranging SHORT, trending_down LONG, trending_down SHORT) —
      identical circuit breaker, no regime isolation
    - Max concurrent positions: 1 (structural, enforced by strategy flow)
    - Max capital deployed: 100% (structural, single position baseline)

Design Notes:
    - equity_peak is cross-trade state: NEVER reset between positions
    - Circuit breaker is portfolio-level and regime-agnostic: drawdown accumulated
      from any regime (trending, volatile, ranging) contributes equally
    - Position limit (max_concurrent_positions=1) is structurally enforced
      by has_position() guard in strategy.py; it is NOT used as a blocking
      condition here because blocking can_trade() also prevents exit execution
    - Drawdown halt intentionally blocks ALL trading (no entry and no exit)
      per risk_prompt.md: "HALT all trading" on breach
"""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine
from echolon.strategy.schemas import RiskOutput


class risk_manager(BaseComponent):
    """
    Risk management component enforcing the mandatory drawdown circuit breaker.

    Constraints (from risk_prompt.md — KEEP):
        - Halts all trading when equity drawdown from peak >= max_drawdown_pct (6.5%)
        - Regime-agnostic: identical protection for trending_up LONG, volatile SHORT,
          ranging LONG, ranging SHORT, trending_down LONG, and trending_down SHORT
          pathways (no per-regime threshold variation)
        - Single position limit structurally enforced by strategy flow (not a blocker here)

    State:
        - equity_peak: High-water mark for portfolio value (cross-trade, never reset)
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Extract owned parameters (from risk_prompt.md parameters section)
        self.max_drawdown_pct = self.params['max_drawdown_pct']
        # max_capital_deployed_pct is structurally enforced via single-position constraint
        # (max_concurrent_positions=1 via has_position() guard in strategy.py ensures at
        # most one position is ever open, bounding capital deployment to one contract's
        # margin at all times). With default=100%, this constraint is always satisfied
        # for a single-lot position on a 200k RMB account. Stored for completeness and
        # potential future enforcement when multi-position support is added.
        self.max_capital_deployed_pct = self.params['max_capital_deployed_pct']

        # Cross-trade state: equity high-water mark
        # Initialized lazily on first can_trade() call
        # NEVER reset between trades - must persist across entire strategy lifetime
        self.equity_peak = None

    def can_trade(self) -> RiskOutput:
        """
        Evaluate risk constraints and determine if trading is permitted.

        Primary check:
            Drawdown from equity peak >= max_drawdown_pct (6.5%) → HALT all trading

        The drawdown is calculated as:
            drawdown_pct = (equity_peak - current_equity) / equity_peak * 100

        Returns:
            RiskOutput with trading_allowed and diagnostic fields
        """
        current_equity = self.portfolio.get_total_value()

        # Initialize equity peak on first invocation
        if self.equity_peak is None:
            self.equity_peak = current_equity

        # Update high-water mark when equity grows beyond previous peak
        if current_equity > self.equity_peak:
            self.equity_peak = current_equity

        # Calculate current drawdown from peak (basis: equity peak)
        current_drawdown_pct = (
            (self.equity_peak - current_equity) / self.equity_peak
        ) * 100.0

        # ── Check: Drawdown circuit breaker ────────────────────────────────
        # Hard constraint per risk_prompt.md (non-negotiable):
        # Threshold 6.5% (range [6.0, 7.0]) with 9.16pp headroom to 15% absolute max
        if current_drawdown_pct >= self.max_drawdown_pct:
            output = RiskOutput(
                trading_allowed=False,
                flatten_positions=True,
                risk_reason=(
                    f'DRAWDOWN HALT: drawdown {current_drawdown_pct:.2f}% '
                    f'>= limit {self.max_drawdown_pct:.1f}% | '
                    f'equity_peak={self.equity_peak:.2f}, '
                    f'current_equity={current_equity:.2f}'
                ),
                current_drawdown_pct=round(current_drawdown_pct, 4),
                equity_peak=self.equity_peak,
                current_equity=current_equity,
            )
            self.log_risk_output(output)
            return output

        # ── All constraints satisfied → trading allowed ─────────────────────
        output = RiskOutput(
            trading_allowed=True,
            flatten_positions=False,
            risk_reason=(
                f'Trading allowed | '
                f'drawdown {current_drawdown_pct:.2f}% '
                f'< limit {self.max_drawdown_pct:.1f}% | '
                f'equity_peak={self.equity_peak:.2f}, '
                f'current_equity={current_equity:.2f}'
            ),
            current_drawdown_pct=round(current_drawdown_pct, 4),
            equity_peak=self.equity_peak,
            current_equity=current_equity,
        )
        self.log_risk_output(output)
        return output
