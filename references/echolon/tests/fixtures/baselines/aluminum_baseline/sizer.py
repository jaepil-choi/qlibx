"""
Position Sizer Component - ATR-Based with Regime-Differentiated Risk (SHFE Aluminum Interday)

Implements ATR-based position sizing with regime-differentiated risk percentages
and marginal rounding rescue for capital-constrained futures environments.

Sizing Formula (sourced from sizer_prompt.md):
    risk_amount       = equity × risk_per_trade_pct / 100
    risk_per_contract = trailing_atr_multiplier × ATR(atr_period) × contract_multiplier
    raw_size          = risk_amount / risk_per_contract

Regime-to-Risk-Pct Mapping (two-tier):
    volatile SHORT:  volatile_regime_risk_per_trade_pct (default 5.3%)
                     — compensates for wider ATR multiplier (3.59x vs ~2.5x)
    all others:      default_risk_per_trade_pct (default 4.5%)
                     — baseline regimes: trending_up LONG, ranging LONG/SHORT,
                       trending_down LONG, trending_down SHORT

Regime-to-Multiplier Mapping (six pathways):
    trending_up   LONG:  trailing_atr_multiplier_trending_up          (default 2.507)
    volatile      SHORT: trailing_atr_multiplier_volatile              (default 3.591)
    ranging       LONG:  trailing_atr_multiplier_ranging_long          (default 2.305)
    ranging       SHORT: trailing_atr_multiplier_ranging_short         (default 2.118)
    trending_down LONG:  trailing_atr_multiplier_trending_down         (default 2.456)
    trending_down SHORT: trailing_atr_multiplier_trending_down_short   (default 2.8)

Marginal Rounding (futures contract indivisibility rescue):
    When raw_size >= marginal_rounding_threshold AND raw_size < 1.0  → round up to 1 lot
    When raw_size < marginal_rounding_threshold                       → blocked (size = 0)

Position Constraints (from sizer_prompt.md):
    max_position_lots = 1 (formula calibrated to yield ~1 lot at median ATR)

Parameters Owned:
    default_risk_per_trade_pct                  [4.0, 5.0]  FLOAT — default 4.5%
    volatile_regime_risk_per_trade_pct          [5.05, 6.0] FLOAT — default 5.3%
    marginal_rounding_threshold                 [0.3, 0.7]  FLOAT — default 0.5
    max_position_lots                           [1, 1]      INT   — default 1
    trailing_atr_multiplier_trending_up         FIXED FLOAT — 2.507365447069778
    trailing_atr_multiplier_volatile            FIXED FLOAT — 3.590769399256032
    trailing_atr_multiplier_ranging_long        FIXED FLOAT — 2.3048729881608385
    trailing_atr_multiplier_ranging_short       FIXED FLOAT — 2.118024386610257
    trailing_atr_multiplier_trending_down       FIXED FLOAT — 2.455981830181817
    trailing_atr_multiplier_trending_down_short FIXED FLOAT — 2.8
    contract_multiplier                         FIXED INT   — 5 (SHFE aluminum)

Parameters Shared (from exit):
    atr_period [14, 20] INT — default 17
"""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import ITradingEngine
from echolon.strategy.schemas import SizerOutput, EntrySignalOutput


class position_sizer(BaseComponent):
    """
    ATR-based position sizer with regime-differentiated risk for SHFE aluminum futures (interday).

    Positions are sized so that the maximum monetary loss per trade (stop distance
    × contract multiplier × lots) equals a regime-specific percentage of current equity.
    Stop distance is derived from the ATR multiplier used by the exit component,
    ensuring size calculation is consistent with actual stop placement.

    Two-tier risk allocation:
        volatile SHORT:  5.3% risk — elevated to compensate for wider ATR stop (3.59×)
        all others:      4.5% risk — baseline for trending_up, ranging, trending_down LONG/SHORT

    Six regime pathways (matching six-pathway entry design):
        trending_up   LONG:  tighter multiplier (2.507×) — trend-continuation upward
        volatile      SHORT: wider   multiplier (3.591×) — downtrend-skewed volatile
        ranging       LONG:  tight   multiplier (2.305×) — mean-reversion LONG, lower vol
        ranging       SHORT: tight   multiplier (2.118×) — mean-reversion SHORT
        trending_down LONG:  mid     multiplier (2.456×) — ADXR momentum LONG
        trending_down SHORT: wider   multiplier (2.8×)   — AD-line SHORT, highest vol
    """

    def __init__(self, trading_engine: ITradingEngine, frequency_context=None, market_adapter=None, **params):
        super().__init__(trading_engine, frequency_context, market_adapter, **params)

        # Sizer-owned risk parameters (two-tier regime-differentiated risk)
        self.default_risk_per_trade_pct = self.params['default_risk_per_trade_pct']
        self.volatile_regime_risk_per_trade_pct = self.params['volatile_regime_risk_per_trade_pct']
        self.marginal_rounding_threshold = self.params['marginal_rounding_threshold']
        self.max_position_lots = self.params['max_position_lots']

        # Shared parameter from exit component (ATR period)
        self.atr_period = self.params['atr_period']

        # Trailing ATR stop multipliers (shared from exit, regime-calibrated)
        self.trailing_atr_multiplier_trending_up = self.params['trailing_atr_multiplier_trending_up']
        self.trailing_atr_multiplier_volatile = self.params['trailing_atr_multiplier_volatile']
        self.trailing_atr_multiplier_ranging_long = self.params['trailing_atr_multiplier_ranging_long']
        self.trailing_atr_multiplier_ranging_short = self.params['trailing_atr_multiplier_ranging_short']
        self.trailing_atr_multiplier_trending_down = self.params['trailing_atr_multiplier_trending_down']
        self.trailing_atr_multiplier_trending_down_short = self.params['trailing_atr_multiplier_trending_down_short']

        # Fixed structural constant — SHFE aluminum: 5 metric tons per lot
        self.contract_multiplier = self.params['contract_multiplier']

    def _select_atr_multiplier(self, signal_direction: str, regime: str) -> tuple:
        """
        Select regime-calibrated ATR stop multiplier for sizing.

        The multiplier is keyed on BOTH regime AND direction, matching the
        six-pathway entry design:
            trending_up   + LONG  → trailing_atr_multiplier_trending_up
            volatile      + SHORT → trailing_atr_multiplier_volatile
            ranging       + LONG  → trailing_atr_multiplier_ranging_long
            ranging       + SHORT → trailing_atr_multiplier_ranging_short
            trending_down + LONG  → trailing_atr_multiplier_trending_down
            trending_down + SHORT → trailing_atr_multiplier_trending_down_short

        Args:
            signal_direction: 'LONG' or 'SHORT' from entry signal
            regime: market regime string from entry signal

        Returns:
            (multiplier: float, regime_label: str) tuple for diagnostics
        """
        if regime == 'trending_up':
            return self.trailing_atr_multiplier_trending_up, 'trending_up'
        elif regime == 'volatile':
            return self.trailing_atr_multiplier_volatile, 'volatile'
        elif regime == 'trending_down' and signal_direction == 'LONG':
            return self.trailing_atr_multiplier_trending_down, 'trending_down_long'
        elif regime == 'trending_down' and signal_direction == 'SHORT':
            return self.trailing_atr_multiplier_trending_down_short, 'trending_down_short'
        elif regime == 'ranging' and signal_direction == 'LONG':
            return self.trailing_atr_multiplier_ranging_long, 'ranging_long'
        elif regime == 'ranging' and signal_direction == 'SHORT':
            return self.trailing_atr_multiplier_ranging_short, 'ranging_short'
        else:
            # Per No Error Handling policy: expose unexpected regime/direction combos immediately.
            raise ValueError(
                f'Unrecognized regime/direction combination: '
                f'regime={regime!r}, signal_direction={signal_direction!r}. '
                f'Valid regimes: trending_up (LONG), volatile (SHORT), '
                f'ranging (LONG/SHORT), trending_down (LONG/SHORT).'
            )

    def _select_risk_pct(self, regime: str) -> float:
        """
        Select regime-differentiated risk percentage.

        volatile regime uses elevated risk (5.3%) to compensate for its 48% wider
        ATR multiplier (3.22× vs 2.4× baseline), ensuring raw_size stays above 1.0
        at median ATR. All other regimes use the baseline risk percentage (4.5%).

        Args:
            regime: market regime string from entry signal

        Returns:
            risk_per_trade_pct as float
        """
        if regime == 'volatile':
            return self.volatile_regime_risk_per_trade_pct
        return self.default_risk_per_trade_pct

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        """
        Calculate position size using ATR-based regime-differentiated risk method.

        Core formula (sourced from sizer_prompt.md):
            risk_amount       = equity × risk_per_trade_pct / 100
            risk_per_contract = trailing_atr_multiplier × ATR(atr_period) × contract_multiplier
            raw_size          = risk_amount / risk_per_contract

        Final sizing logic (max_position_lots = 1):
            raw_size >= 1.0:                                  cap to max_position_lots (→ 1 lot)
            marginal_rounding_threshold <= raw_size < 1.0:   rescue → 1 lot
            raw_size < marginal_rounding_threshold:           block → 0 lots

        Args:
            signal_data: EntrySignalOutput from entry component (attribute access only)

        Returns:
            SizerOutput with calculated_size, raw_size, signal_direction, sizing_reason
            and full diagnostic fields (atr_value, risk_amount, risk_per_contract, etc.)
        """
        signal_direction = signal_data.signal
        regime = signal_data.regime

        # Gather portfolio equity and current ATR (Tier 1 indicator: atr_{period})
        equity = self.portfolio.get_total_value()
        atr = self.get_indicator(f'atr_{self.atr_period}')

        # Select regime-calibrated multiplier and risk percentage
        trailing_atr_multiplier, regime_label = self._select_atr_multiplier(signal_direction, regime)
        risk_per_trade_pct = self._select_risk_pct(regime)

        # ── Core ATR-based Fixed Percentage Risk formula ─────────────────────
        # risk_amount: total RMB capital committed to risk for this trade
        risk_amount = equity * risk_per_trade_pct / 100.0

        # risk_per_contract: monetary stop distance per contract
        #   stop_distance (RMB/ton) = trailing_atr_multiplier × ATR
        #   risk_per_contract (RMB) = stop_distance × contract_multiplier (tons)
        #
        # Note: SHFE aluminum ATR is denominated in RMB/ton (price units), so
        # ATR × contract_multiplier directly yields RMB/contract without additional
        # price scaling.
        risk_per_contract = trailing_atr_multiplier * atr * self.contract_multiplier

        # Compute raw (un-rounded) number of contracts
        computed_raw_size = risk_amount / risk_per_contract

        # ── Sizing logic: marginal rounding + floor ──────────────────────────
        rounding_applied = False
        trade_blocked = False
        max_lots = float(self.max_position_lots)

        if computed_raw_size >= 1.0:
            # Normal case: formula yields ≥ 1 lot; cap at max_position_lots
            effective_raw_size = max_lots
            rounding_applied = False
        elif computed_raw_size >= self.marginal_rounding_threshold:
            # Marginal rounding rescue: near-viable signal elevated to 1 lot
            # Applies when extreme ATR compresses raw_size below 1 but above threshold
            effective_raw_size = max_lots
            rounding_applied = True
        else:
            # Below rescue threshold: trade blocked to prevent over-leveraging
            effective_raw_size = 0.0
            trade_blocked = True

        # Validate and convert to non-negative integer (MANDATORY platform call)
        calculated_size = self.validate_and_convert_position_size(effective_raw_size)

        # ── Compose diagnostic sizing reason ────────────────────────────────
        base_info = (
            f'equity={equity:.0f} RMB, '
            f'risk_pct={risk_per_trade_pct:.1f}%, '
            f'risk_amount={risk_amount:.2f} RMB, '
            f'ATR({self.atr_period})={atr:.2f}, '
            f'multiplier={trailing_atr_multiplier:.3f}x, '
            f'contract_mult={self.contract_multiplier}, '
            f'risk_per_contract={risk_per_contract:.2f} RMB, '
            f'regime={regime_label}'
        )

        if trade_blocked:
            sizing_reason = (
                f'{signal_direction} BLOCKED: raw_size={computed_raw_size:.4f} '
                f'< marginal_threshold={self.marginal_rounding_threshold:.2f}. '
                f'Trade not executable — ATR too high relative to equity. '
                f'[{base_info}]'
            )
        elif rounding_applied:
            sizing_reason = (
                f'{signal_direction} MARGINAL RESCUE: '
                f'raw_size={computed_raw_size:.4f} in '
                f'[{self.marginal_rounding_threshold:.2f}, 1.0) → rounded up to 1 lot. '
                f'[{base_info}]'
            )
        else:
            sizing_reason = (
                f'{signal_direction} NORMAL: '
                f'raw_size={computed_raw_size:.4f} → {calculated_size} lot(s). '
                f'[{base_info}]'
            )

        output = SizerOutput(
            calculated_size=calculated_size,
            signal_direction=signal_direction,
            sizing_reason=sizing_reason,
            raw_size=computed_raw_size,  # True formula raw value (pre-cap/pre-rescue)
            # Diagnostic extra fields (SizerOutput uses extra='allow')
            effective_raw_size=effective_raw_size,  # Post-cap/post-rescue value (0.0 or 1.0)
            equity=equity,
            atr_value=atr,
            risk_amount=risk_amount,
            risk_per_contract=risk_per_contract,
            trailing_atr_multiplier=trailing_atr_multiplier,
            regime_label=regime_label,
            risk_per_trade_pct=risk_per_trade_pct,
            rounding_applied=rounding_applied,
            trade_blocked=trade_blocked,
        )

        self.log_sizer_output(output)
        return output
