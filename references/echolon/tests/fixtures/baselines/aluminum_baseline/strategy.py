"""
Strategy Coordinator - Multi-Regime Momentum Strategy (SHFE Aluminum Interday)
===============================================================================

Implements a six-pathway regime-momentum approach on SHFE aluminum futures
(daily bars), covering 100% of market regimes with regime-calibrated ATR
trailing stops, MFE-based profit targets, and a mandatory 6.5% drawdown
circuit breaker.

Entry Pathways (from entry_prompt.md):
    Pathway 1 - TRENDING_UP LONG:
        IF market_regime == 'trending_up' AND CCI(period) > cci_threshold
        THEN ENTER LONG
        Rationale: IC = +0.215 (STRONG, Bonferroni significant); high CCI predicts
        momentum continuation; signal frequency = 11.79%.

    Pathway 2 - VOLATILE SHORT:
        IF market_regime == 'volatile' AND OBV > obv_threshold
        THEN ENTER SHORT
        Rationale: IC = -0.528 (STRONG, highest regime-specific IC); high OBV
        predicts lower returns in downtrend-skewed volatile regime;
        signal frequency = 12.10%.

    Pathway 3 - RANGING LONG:
        IF market_regime == 'ranging' AND macd_histogram > macd_histogram_threshold
        THEN ENTER LONG
        Rationale: IC = +0.206 (STRONG); positive histogram shift predicts
        mean-reversion bounce in ranging conditions;
        signal frequency = 10.14%.

    Pathway 4 - RANGING SHORT:
        IF market_regime == 'ranging' AND bbands_pct_b > bbands_pct_b_short_threshold
        THEN ENTER SHORT  (evaluated when Pathway 3 not triggered)
        Rationale: IC = +0.148 (STRONG); price near upper band predicts
        mean-reversion SHORT in ranging regime (replaces decayed TEMA);
        expected frequency = ~40-50 trades/year.

    Pathway 5 - TRENDING_DOWN LONG:
        IF market_regime == 'trending_down' AND adxr(period) > adxr_threshold
        THEN ENTER LONG
        Rationale: IC = +0.277 (STRONG, asymmetric positive tail 0.610);
        strong trend direction supports LONG momentum;
        expected frequency = ~15-20 trades/year.
        PRESERVED: v3.5/v3.6 historical OOS collapse precedent.

    Pathway 6 - TRENDING_DOWN SHORT:
        IF market_regime == 'trending_down' AND ad > ad_threshold
        THEN ENTER SHORT  (evaluated when Pathway 5 not triggered)
        Rationale: IC = -0.356 (STRONG), Pos tail IC = -0.496; high Chaikin
        A/D accumulation predicts decline in negative-drift regime;
        expected frequency = ~3.6 signals/year.

Exit Mechanism (from exit_prompt.md):
    Three-layer exit per pathway (priority order):
    Layer 2 - MFE Profit Target (primary): entry +/- recent_range x capture_pct
        - Trending LONG (up/down):    profit_capture_pct (0.78 default)
        - Volatile/Ranging:           profit_capture_pct x 0.9375
        - Trending DOWN SHORT (new):  profit_capture_trending_down_short_pct (0.85)
    Layer 1 - ATR Trailing Stop (safety net): regime-calibrated multipliers
        - LONG  (trending_up):         trail below highest close at 2.357383x ATR
        - SHORT (volatile):            trail above lowest  close at 3.215562x ATR
        - LONG  (ranging):             trail below highest close at 2.172573x ATR
        - SHORT (ranging):             trail above lowest  close at 2.3255x   ATR
        - LONG  (trending_down):       trail below highest close at 2.610751x ATR
        - SHORT (trending_down, new):  trail above lowest  close at 2.8x      ATR
    Layer 3 - Time Backstop (regime-extended):
        - Trending LONG (up/down): max_holding_trending_bars (25, range [20, 30])
        - Trending DOWN SHORT:     max_holding_trending_short_bars (18, range [15, 22])
        - Ranging/Volatile:        max_holding_standard_bars (FIXED=20)

Risk Controls (from risk_prompt.md):
    - Mandatory 6.5% drawdown circuit breaker -> HALT all trading + flatten position

Sizing (from sizer_prompt.md):
    Regime-differentiated ATR-based risk:
        baseline (trending_up, ranging, trending_down): 4.5% risk/trade
        volatile SHORT: 5.3% risk/trade (compensates 48% wider ATR multiplier)
    Marginal rounding rescue (threshold 0.5) for SHFE aluminum contract (5 t/lot).

Orchestration (per strategy_overview.md):
    1. Risk Assessment  -> risk_manager.can_trade()
    2. Circuit Breaker  -> flatten open position if halted, return
    3. Exit Evaluation  -> exit_rule.should_exit()  (when position held)
    4. Entry Signal     -> entry_rule.generate_signal()  (when no position)
    5. Position Sizing  -> position_sizer.calculate_size()
    6. Order Execution  -> self.entry() / self.exit()

Infrastructure (automatic - DO NOT implement):
    - Contract expiry forced exits: ForcedExitStrategyHook (processed before _execute_bar)
    - Component initialisation: BaseStrategy.setup_components()
    - State persistence: save_state() / restore_state()
"""

from echolon.strategy.base import BaseStrategy
from echolon.strategy.interfaces import ITradingEngine, OrderIntent


class strategy_main(BaseStrategy):
    """
    Multi-Regime Momentum Strategy for SHFE Aluminum Futures (Interday).

    Six momentum-aligned entry pathways cover 100% of market regimes via
    regime-specific IC signals:
      - TRENDING_UP regime LONG entries via CCI oscillator (IC=+0.215)
      - VOLATILE regime SHORT entries via OBV accumulation/distribution (IC=-0.528)
      - RANGING regime LONG entries via MACD histogram mean-reversion (IC=+0.206)
      - RANGING regime SHORT entries via BBands %B mean-reversion (IC=+0.148)
      - TRENDING_DOWN regime LONG entries via ADXR momentum (IC=+0.277 STRONG)
      - TRENDING_DOWN regime SHORT entries via Chaikin A/D Line (IC=-0.356 STRONG)

    Exits use a three-layer structure:
      Layer 2 (primary):  MFE-based profit target at 78% capture (trending LONG),
                          73.125% (volatile/ranging), or 85% capture (trending_down
                          SHORT — aggressive for strong-trend momentum signal).
      Layer 1 (safety):   ATR trailing stops with regime-calibrated multipliers
                          (2.357383x trending_up LONG, 3.215562x volatile SHORT,
                          2.172573x ranging LONG, 2.3255x ranging SHORT,
                          2.610751x trending_down LONG, 2.8x trending_down SHORT).
      Layer 3 (backstop): Regime-extended time limit (25 bars trending LONG,
                          18 bars trending_down SHORT, 20 bars ranging/volatile).

    Sizing uses regime-differentiated risk:
      - Baseline regimes (trending_up, trending_down, ranging): 4.5% risk/trade
      - Volatile SHORT: 5.3% risk/trade (compensates wider ATR stop)

    A 6.5% peak-equity drawdown circuit breaker provides mandatory capital
    protection across all six pathways.
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Components are automatically initialised by BaseStrategy.setup_components()
        # during on_start() -> self.entry_rule, self.exit_rule,
        #                       self.risk_manager, self.position_sizer

    def _on_strategy_start(self) -> None:
        """Custom startup logging after all components are initialised."""
        self.log("Multi-Regime Momentum Strategy - SHFE Aluminum (Interday)")
        self.log(
            f"Entry Pathway 1 (trending_up LONG): "
            f"CCI(period={self.entry_rule.cci_period}, "
            f"threshold={self.entry_rule.cci_threshold}) - IC=+0.215"
        )
        self.log(
            f"Entry Pathway 2 (volatile SHORT): "
            f"OBV(threshold={self.entry_rule.obv_threshold:.0f}) - IC=-0.528"
        )
        self.log(
            f"Entry Pathway 3 (ranging LONG): "
            f"MACD histogram(threshold={self.entry_rule.macd_histogram_threshold:.4f}) "
            f"- IC=+0.206"
        )
        self.log(
            f"Entry Pathway 4 (ranging SHORT): "
            f"BBands %B(threshold={self.entry_rule.bbands_pct_b_short_threshold:.2f}) "
            f"- IC=+0.148 (replaces decayed TEMA)"
        )
        self.log(
            f"Entry Pathway 5 (trending_down LONG): "
            f"ADXR(period={self.entry_rule.adxr_period}, "
            f"threshold={self.entry_rule.adxr_threshold:.1f}) - IC=+0.277 STRONG"
        )
        self.log(
            f"Entry Pathway 6 (trending_down SHORT): "
            f"AD(threshold={self.entry_rule.ad_threshold:.0f}) "
            f"- IC=-0.356 STRONG (Pos tail IC=-0.496, ~3.6 signals/year)"
        )
        self.log(
            f"Exit Layer 1 (ATR trailing stop): "
            f"trending_up mult={self.exit_rule.atr_multiplier_trending_up}x | "
            f"volatile mult={self.exit_rule.atr_multiplier_volatile}x | "
            f"ranging_long mult={self.exit_rule.atr_multiplier_ranging_long}x | "
            f"ranging_short mult={self.exit_rule.atr_multiplier_ranging_short}x | "
            f"trending_down mult={self.exit_rule.atr_multiplier_trending_down}x | "
            f"trending_down_short mult={self.exit_rule.atr_multiplier_trending_down_short}x | "
            f"ATR period={self.exit_rule.atr_period}"
        )
        self.log(
            f"Exit Layer 2 (MFE profit target): "
            f"profit_capture_pct={self.exit_rule.profit_capture_pct:.2f} | "
            f"profit_capture_trending_down_short_pct="
            f"{self.exit_rule.profit_capture_trending_down_short_pct:.2f} | "
            f"mfe_lookback_window={self.exit_rule.mfe_lookback_window} bars"
        )
        self.log(
            f"Exit Layer 3 (time backstop): "
            f"max_holding_trending_bars={self.exit_rule.max_holding_trending_bars} | "
            f"max_holding_trending_short_bars={self.exit_rule.max_holding_trending_short_bars} | "
            f"max_holding_standard_bars={self.exit_rule.max_holding_standard_bars}"
        )
        self.log(
            f"Risk: max_drawdown_pct={self.risk_manager.max_drawdown_pct}%"
        )
        self.log(
            f"Sizing: default_risk_per_trade_pct={self.position_sizer.default_risk_per_trade_pct}% | "
            f"volatile_regime_risk_per_trade_pct={self.position_sizer.volatile_regime_risk_per_trade_pct}% | "
            f"marginal_rounding_threshold={self.position_sizer.marginal_rounding_threshold}"
        )

    def _execute_bar(self) -> None:
        """
        Main trading logic executed on each bar.

        Override _execute_bar() (NOT on_bar()) per BaseStrategy template method pattern.
        Contract expiry forced exits are processed automatically BEFORE this method by
        ForcedExitStrategyHook; no manual expiry handling is required here.

        Orchestration:
            1. Risk check  - drawdown circuit breaker evaluation
            2. If halted   - flatten open position (protect capital) then return
            3. If position - evaluate three-layer exit (MFE target / ATR stop / time backstop)
            4. If no position - generate six-pathway entry signal, size, submit order
        """
        # =====================================================================
        # Step 1: Risk Assessment - Drawdown Circuit Breaker
        # =====================================================================
        risk_output = self.risk_manager.can_trade()

        # Circuit breaker halt: flatten open position then suspend all activity.
        # Per risk_prompt.md: "intervention_action: HALT all trading + flatten positions"
        # flatten_positions=True is set explicitly by risk_manager on drawdown breach.
        if not risk_output.trading_allowed:
            self.log(f"Trading halted: {risk_output.risk_reason}")
            if risk_output.flatten_positions and self.has_position() and not self.has_pending_orders():
                if self.is_long_position():
                    self.exit(OrderIntent.EXIT_LONG)
                else:
                    self.exit(OrderIntent.EXIT_SHORT)
            return

        # =====================================================================
        # Step 2: Exit Evaluation (when position is held)
        # =====================================================================
        # Evaluate exits BEFORE entries to ensure clean position management.
        # has_pending_orders() guard prevents duplicate order submission
        # (Backtrader market orders execute at NEXT bar's open, not immediately).
        if self.has_position() and not self.has_pending_orders():
            exit_output = self.exit_rule.should_exit()

            if exit_output.should_exit:
                self.exit(exit_output.intent)
                return

        # =====================================================================
        # Step 3: Entry Signal Generation (when no position is held)
        # =====================================================================
        # Only evaluate new entries when:
        #   - Risk check passed (trading_allowed=True)
        #   - No current position (single-position constraint from risk_prompt.md)
        #   - No pending orders (prevents over-submission on consecutive signal bars)
        if not self.has_position() and not self.has_pending_orders():
            entry_output = self.entry_rule.generate_signal()

            if entry_output.signal != 'HOLD':
                # -- Step 4: Position Sizing -----------------------------------------------
                sizer_output = self.position_sizer.calculate_size(entry_output)

                # -- Step 5: Order Submission ----------------------------------------------
                if sizer_output.calculated_size > 0:
                    self.entry(entry_output.intent, sizer_output.calculated_size)

    def on_stop(self) -> None:
        """Called when strategy stops - log final state."""
        self.log("Strategy stopped - Multi-Regime Momentum (SHFE Aluminum Interday)")
        super().on_stop()
