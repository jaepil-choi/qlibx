"""
Exit Component - Three-Layer Exit: MFE Profit Target + ATR Trailing Stop + Time Backstop

Layer 1 - ATR Trailing Stop (safety net, PRESERVED):
    6-pathway regime multipliers: trending_up=2.357383, volatile=3.215562,
    ranging_long=2.172573, ranging_short=2.3255, trending_down=2.610751,
    trending_down_short=2.8 (NEW — wider for highest volatility regime 17.61%).

Layer 2 - MFE-Based Profit Target (primary):
    Computed once at entry: entry ± recent_close_range × effective_capture_pct.
    Priority over trailing stop ("Target before stop; stop protects if missed").
    Trending LONG: profit_capture_pct; trending_down SHORT: profit_capture_trending_down_short_pct=0.85;
    volatile/ranging: profit_capture_pct × 0.9375.

Layer 3 - Time Backstop (regime-specific):
    trending_up/down LONG → max_holding_trending_bars (25 default, range 20-30).
    trending_down SHORT   → max_holding_trending_short_bars (18 default, range 15-22).
    ranging/volatile      → max_holding_standard_bars (FIXED=20).

Parameters: atr_period(17), mfe_lookback_window(16), max_holding_trending_bars(25),
    profit_capture_pct(0.78), profit_capture_trending_down_short_pct(0.85),
    max_holding_trending_short_bars(18), atr_multiplier_*(FIXED PRESERVED),
    max_holding_standard_bars(20).

Per-trade state: trailing_stop_price, highest/lowest_close_since_entry,
    bars_in_position, mfe_profit_target_price.
Cross-trade state (not reset): close_history (rolling deque, mfe_lookback_window bars).
"""

from collections import deque
from typing import Dict, Any, Optional

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine, OrderIntent
from echolon.strategy.schemas import ExitSignalOutput


class exit_rule(BaseComponent):
    """
    Three-layer exit: MFE profit target + ATR trailing stop + regime-specific time backstop.

    Layer 2 (primary):  MFE profit target — price reaches entry ± range × capture_pct.
                        trending_down SHORT uses aggressive profit_capture_trending_down_short_pct=0.85.
    Layer 1 (safety):   ATR trailing stop — 6-pathway regime-calibrated multipliers.
                        trending_down SHORT uses wider atr_multiplier_trending_down_short=2.8.
    Layer 3 (backstop): Time limit — trending LONG extended (25), trending_down SHORT (18),
                        ranging/volatile fixed (20).
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # ── Owned parameters (from exit_prompt.md → ExitParameters) ──────────
        self.atr_period: int = self.params['atr_period']
        self.mfe_lookback_window: int = self.params['mfe_lookback_window']
        self.max_holding_trending_bars: int = int(self.params['max_holding_trending_bars'])
        self.max_holding_trending_short_bars: int = int(self.params['max_holding_trending_short_bars'])
        self.profit_capture_pct: float = self.params['profit_capture_pct']
        self.profit_capture_trending_down_short_pct: float = self.params['profit_capture_trending_down_short_pct']
        self.atr_multiplier_trending_up: float = self.params['atr_multiplier_trending_up']
        self.atr_multiplier_volatile: float = self.params['atr_multiplier_volatile']
        self.atr_multiplier_ranging_long: float = self.params['atr_multiplier_ranging_long']
        self.atr_multiplier_ranging_short: float = self.params['atr_multiplier_ranging_short']
        self.atr_multiplier_trending_down: float = self.params['atr_multiplier_trending_down']
        self.atr_multiplier_trending_down_short: float = self.params['atr_multiplier_trending_down_short']

        # FIXED — standard max holding for ranging/volatile pathways
        self.max_holding_standard_bars: int = int(self.params['max_holding_standard_bars'])

        # ── Per-trade state variables ─────────────────────────────────────────
        # Initialised to None/0; restored via _restore_component_specific_state()
        # in live trading. Reset by _reset_state() on each trade completion.
        self.trailing_stop_price: Optional[float] = None
        self.highest_close_since_entry: Optional[float] = None
        self.lowest_close_since_entry: Optional[float] = None
        self.bars_in_position: int = 0
        self.mfe_profit_target_price: Optional[float] = None

        # ── Cross-trade state variable ────────────────────────────────────────
        # Rolling window of recent closes for MFE estimation at entry.
        # NOT reset per trade — maintains continuous history across all trades.
        # Updated every bar (including bars with no position) so MFE estimate
        # is always available when a new trade starts.
        self.close_history: deque = deque(maxlen=self.mfe_lookback_window)

    # ── State management trio ─────────────────────────────────────────────────

    def _reset_state(self) -> None:
        """
        Reset all per-trade state to initial values.

        Called:
        (1) Inside should_exit() when no position is present (clean start).
        (2) After should_exit() returns True (deploy infrastructure resets
            again externally for state file consistency).

        Per-trade variables reset: trailing_stop_price, highest/lowest close
        extremes, bars_in_position, mfe_profit_target_price.
        Cross-trade variable (close_history) is NOT reset — it maintains
        a continuous rolling window of closes across trades.
        """
        self.trailing_stop_price = None
        self.highest_close_since_entry = None
        self.lowest_close_since_entry = None
        self.bars_in_position = 0
        self.mfe_profit_target_price = None

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """
        Return exit-specific state dict for live trading persistence.

        Must include every variable that could differ across bars and needs
        to survive between process restarts (live trading).
        close_history serialised as list; restored as deque.
        """
        return {
            'trailing_stop_price': self.trailing_stop_price,
            'highest_close_since_entry': self.highest_close_since_entry,
            'lowest_close_since_entry': self.lowest_close_since_entry,
            'bars_in_position': self.bars_in_position,
            'mfe_profit_target_price': self.mfe_profit_target_price,
            'close_history': list(self.close_history),
        }

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """
        Restore exit-specific state from persistence dict.

        Keys must exactly match those in _get_component_specific_state().
        close_history is reconstructed as a bounded deque from the stored list.
        """
        self.trailing_stop_price = state['trailing_stop_price']
        self.highest_close_since_entry = state['highest_close_since_entry']
        self.lowest_close_since_entry = state['lowest_close_since_entry']
        self.bars_in_position = state['bars_in_position']
        self.mfe_profit_target_price = state['mfe_profit_target_price']
        self.close_history = deque(state['close_history'], maxlen=self.mfe_lookback_window)

    # ── Primary exit method ───────────────────────────────────────────────────

    def should_exit(self) -> ExitSignalOutput:
        """
        Evaluate three-layer exit conditions and return ExitSignalOutput.

        Order: (1) update close_history always; (2) no-position guard; (3) increment
        bar counter; (4) fetch ATR + market_regime; (5) select 6-pathway multiplier;
        (6) select regime max_holding_bars; (7) compute effective_capture_pct;
        (8) initialise trailing stop + profit target on first bar; (9) ratchet stop;
        (10) check exits: time backstop → profit target → trailing stop → holding.
        """
        # ── Fetch current close; update rolling history (always, every bar) ───
        # close_history is cross-trade: updated whether or not a position is open,
        # so that a fresh MFE estimate is available at the start of every new trade.
        current_bar = self.get_current_bar()
        current_close: float = current_bar['close']
        self.close_history.append(current_close)

        position = self.portfolio.get_position()

        # ── Guard: no position ────────────────────────────────────────────────
        if position is None or position.size == 0:
            self._reset_state()
            output = ExitSignalOutput(
                should_exit=False,
                exit_reason='No position to exit',
                position_size=0.0,
                bars_since_entry=0,
                intent=None,
            )
            self.log_exit_output(output)
            return output

        # ── Increment position bar counter ────────────────────────────────────
        self.bars_in_position += 1

        # ── Fetch market data ─────────────────────────────────────────────────
        entry_price: float = position.avg_price
        is_long: bool = position.direction == 'LONG'

        # ATR — Tier 1 indicator; name format: f'atr_{period}'
        atr: float = self.get_indicator(f'atr_{self.atr_period}')

        # market_regime — interday method (Tier 2 special-params indicator)
        market_regime: str = self.get_market_regime()

        # ── Select regime-specific ATR multiplier (6-pathway) ─────────────────
        # Primary: match (market_regime, direction) to exit_prompt.md pathways.
        # Fallback: direction-based selection handles regime transitions
        #           (position entered in one regime, evaluated in another).
        # Regime transition fallback design (intentional — not in exit_prompt.md):
        #   Conservative direction-based defaults chosen to preserve capital:
        #   LONG fallback → atr_multiplier_trending_up (tightest LONG multiplier, 2.36x)
        #   SHORT fallback → atr_multiplier_volatile   (widest SHORT multiplier, 3.22x)
        #   This ensures the trailing stop is never more permissive than the entry
        #   regime's calibration, guarding against adverse regime transitions.
        if market_regime == 'trending_up' and is_long:
            atr_multiplier: float = self.atr_multiplier_trending_up
        elif market_regime == 'volatile' and not is_long:
            atr_multiplier: float = self.atr_multiplier_volatile
        elif market_regime == 'ranging' and is_long:
            atr_multiplier: float = self.atr_multiplier_ranging_long
        elif market_regime == 'ranging' and not is_long:
            atr_multiplier: float = self.atr_multiplier_ranging_short
        elif market_regime == 'trending_down' and is_long:
            atr_multiplier: float = self.atr_multiplier_trending_down
        elif market_regime == 'trending_down' and not is_long:
            # NEW: trending_down SHORT uses wider stop (2.8) for highest volatility regime
            atr_multiplier: float = self.atr_multiplier_trending_down_short
        else:
            # Regime transition fallback: use direction-based baseline multipliers
            atr_multiplier = self.atr_multiplier_trending_up if is_long else self.atr_multiplier_volatile

        stop_distance: float = atr * atr_multiplier

        # ── Select regime-specific max holding period (Layer 3) ───────────────
        # Trending LONG (up/down): extended holding per exit_prompt.md.
        # Trending_down SHORT: shorter than LONG counterpart — faster SHORT exhaustion.
        # Ranging and volatile pathways: standard FIXED holding period.
        if market_regime in ('trending_up', 'trending_down') and is_long:
            max_holding_bars: int = self.max_holding_trending_bars
        elif market_regime == 'trending_down' and not is_long:
            max_holding_bars: int = self.max_holding_trending_short_bars
        else:
            max_holding_bars: int = self.max_holding_standard_bars

        # ── Compute regime-specific profit capture percentage (Layer 2) ────────
        # Trending LONG: use profit_capture_pct directly.
        # Trending_down SHORT: aggressive profit_capture_trending_down_short_pct=0.85
        #   (IC -0.356 strong-trend momentum signal, exceeds standard 0.78).
        # Volatile/ranging: scale by 0.9375 (mean-reversion adjusted).
        if market_regime in ('trending_up', 'trending_down') and is_long:
            effective_capture_pct: float = self.profit_capture_pct
        elif market_regime == 'trending_down' and not is_long:
            effective_capture_pct: float = self.profit_capture_trending_down_short_pct
        else:
            effective_capture_pct: float = self.profit_capture_pct * 0.9375

        # ── Initialise trailing stop and profit target on first bar ───────────
        # Use direction-specific extreme as initialisation sentinel — correctly
        # handles re-entry after force-exit (contract expiry / circuit breaker)
        # where trailing_stop_price may be non-None from the prior trade.
        if is_long:
            if self.highest_close_since_entry is None:
                # First bar of new LONG trade (or re-entry after force-exit of SHORT)
                self.highest_close_since_entry = entry_price
                self.lowest_close_since_entry = None   # Clear stale SHORT extreme
                self.trailing_stop_price = entry_price - stop_distance

                # MFE-based profit target (Layer 2): computed once at entry.
                # MFE estimate = max-minus-min of recent mfe_lookback_window closes.
                # Fallback (insufficient history): stop_distance × effective_capture_pct.
                if len(self.close_history) >= self.mfe_lookback_window:
                    recent_range = max(self.close_history) - min(self.close_history)
                    self.mfe_profit_target_price = entry_price + recent_range * effective_capture_pct
                else:
                    self.mfe_profit_target_price = entry_price + stop_distance * effective_capture_pct
        else:
            if self.lowest_close_since_entry is None:
                # First bar of new SHORT trade (or re-entry after force-exit of LONG)
                self.lowest_close_since_entry = entry_price
                self.highest_close_since_entry = None  # Clear stale LONG extreme
                self.trailing_stop_price = entry_price + stop_distance

                if len(self.close_history) >= self.mfe_lookback_window:
                    recent_range = max(self.close_history) - min(self.close_history)
                    self.mfe_profit_target_price = entry_price - recent_range * effective_capture_pct
                else:
                    self.mfe_profit_target_price = entry_price - stop_distance * effective_capture_pct

        # ── Update trailing stop on new closing extreme ───────────────────────
        if is_long:
            # Trail UPWARD: raise stop when a new closing high is established
            if current_close > self.highest_close_since_entry:
                self.highest_close_since_entry = current_close
                new_stop = self.highest_close_since_entry - stop_distance
                # Enforce ratchet: stop only moves upward, never retreats
                if new_stop > self.trailing_stop_price:
                    self.trailing_stop_price = new_stop
        else:
            # Trail DOWNWARD: lower stop when a new closing low is established
            if current_close < self.lowest_close_since_entry:
                self.lowest_close_since_entry = current_close
                new_stop = self.lowest_close_since_entry + stop_distance
                # Enforce ratchet: stop only moves downward, never retreats
                if new_stop < self.trailing_stop_price:
                    self.trailing_stop_price = new_stop

        # ── Evaluate exit conditions ──────────────────────────────────────────
        should_exit: bool = False
        exit_reason: str = ''
        intent: Optional[OrderIntent] = (
            OrderIntent.EXIT_LONG if is_long else OrderIntent.EXIT_SHORT
        )

        # Layer 3: Time backstop — regime-specific max holding period enforced first
        if self.bars_in_position >= max_holding_bars:
            should_exit = True
            exit_reason = (
                f'TIME BACKSTOP: bars {self.bars_in_position} >= {max_holding_bars} | '
                f'regime={market_regime}, '
                f'close={current_close:.2f}, stop={self.trailing_stop_price:.2f}, '
                f'target={self.mfe_profit_target_price:.2f}, ATR={atr:.2f}'
            )

        # Layer 2 (LONG): MFE profit target — primary exit, priority over trailing stop
        elif (is_long and current_close >= self.mfe_profit_target_price):
            should_exit = True
            exit_reason = (
                f'PROFIT TARGET HIT (LONG): close {current_close:.2f} >= '
                f'target {self.mfe_profit_target_price:.2f} | '
                f'regime={market_regime}, entry={entry_price:.2f}, '
                f'capture_pct={effective_capture_pct:.4f}, ATR={atr:.2f}'
            )

        # Layer 2 (SHORT): MFE profit target
        elif (not is_long and current_close <= self.mfe_profit_target_price):
            should_exit = True
            exit_reason = (
                f'PROFIT TARGET HIT (SHORT): close {current_close:.2f} <= '
                f'target {self.mfe_profit_target_price:.2f} | '
                f'regime={market_regime}, entry={entry_price:.2f}, '
                f'capture_pct={effective_capture_pct:.4f}, ATR={atr:.2f}'
            )

        # Layer 1 (LONG): ATR trailing stop — safety net if profit target missed
        elif is_long and current_close <= self.trailing_stop_price:
            should_exit = True
            exit_reason = (
                f'TRAILING STOP HIT (LONG): close {current_close:.2f} <= '
                f'stop {self.trailing_stop_price:.2f} | '
                f'regime={market_regime}, '
                f'highest_close={self.highest_close_since_entry:.2f}, '
                f'ATR={atr:.2f}, mult={atr_multiplier:.2f}'
            )

        # Layer 1 (SHORT): ATR trailing stop
        elif not is_long and current_close >= self.trailing_stop_price:
            should_exit = True
            exit_reason = (
                f'TRAILING STOP HIT (SHORT): close {current_close:.2f} >= '
                f'stop {self.trailing_stop_price:.2f} | '
                f'regime={market_regime}, '
                f'lowest_close={self.lowest_close_since_entry:.2f}, '
                f'ATR={atr:.2f}, mult={atr_multiplier:.2f}'
            )

        # ── Holding (no exit triggered) ───────────────────────────────────────
        else:
            intent = None  # No exit intent while position is being held
            direction_label = 'LONG' if is_long else 'SHORT'
            extreme_label = (
                f'highest_close={self.highest_close_since_entry:.2f}'
                if is_long
                else f'lowest_close={self.lowest_close_since_entry:.2f}'
            )
            exit_reason = (
                f'Holding {direction_label} '
                f'(bar {self.bars_in_position}/{max_holding_bars}): '
                f'regime={market_regime}, '
                f'close={current_close:.2f}, '
                f'stop={self.trailing_stop_price:.2f}, '
                f'{extreme_label}, '
                f'target={self.mfe_profit_target_price:.2f}, '
                f'ATR={atr:.2f}, mult={atr_multiplier:.2f}'
            )

        # ── Capture diagnostic values before state reset ──────────────────────
        # Preserve pre-reset values so the output reflects the state
        # that caused the exit decision.
        final_bars: int = self.bars_in_position
        final_stop: Optional[float] = self.trailing_stop_price
        final_highest: Optional[float] = self.highest_close_since_entry
        final_lowest: Optional[float] = self.lowest_close_since_entry
        final_target: Optional[float] = self.mfe_profit_target_price

        # ── Reset per-trade state on exit ─────────────────────────────────────
        # Ensures clean state for the next trade (backtest + deploy consistency).
        # close_history is NOT reset — it continues rolling across trades.
        if should_exit:
            self._reset_state()

        # ── Build and return output ───────────────────────────────────────────
        output = ExitSignalOutput(
            should_exit=should_exit,
            exit_reason=exit_reason,
            position_size=abs(position.size),
            bars_since_entry=final_bars,
            intent=intent,
            # Diagnostic fields (strategy-specific, allowed via extra='allow')
            market_regime=market_regime,
            atr_value=round(atr, 4),
            atr_multiplier=atr_multiplier,
            trailing_stop_price=final_stop,
            highest_close_since_entry=final_highest,
            lowest_close_since_entry=final_lowest,
            current_close=current_close,
            mfe_profit_target_price=final_target,
            effective_capture_pct=round(effective_capture_pct, 4),
        )

        self.log_exit_output(output)
        return output
