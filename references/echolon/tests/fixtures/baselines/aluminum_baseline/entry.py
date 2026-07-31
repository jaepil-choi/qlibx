"""
Entry Component - Multi-Regime Aluminum Momentum Strategy (SHFE Interday)

Generates entry signals via six regime-conditional momentum pathways:

  Pathway 1: Regime trending_up   -> cci(period) > cci_threshold               -> LONG
             IC = +0.215 (STRONG) for 20D horizon, momentum continuation
             in trending markets. Signal frequency = 11.79%.

  Pathway 2: Regime volatile      -> obv > obv_threshold                        -> SHORT
             IC = -0.528 (STRONG) for 20D horizon, high OBV predicts
             negative returns in downtrend-skewed volatile regime.
             Signal frequency = 12.10%.

  Pathway 3: Regime ranging       -> macd_histogram > macd_histogram_threshold  -> LONG
             IC = +0.206 (STRONG) for 20D horizon, positive histogram shift
             predicts mean-reversion bounce in ranging conditions.
             Signal frequency = 10.14%.

  Pathway 4: Regime ranging       -> bbands_pct_b > bbands_pct_b_short_threshold -> SHORT
             IC = +0.148 (STRONG), HIGH %B indicates price near upper band,
             mean-reversion SHORT in ranging regime. Replaces decayed TEMA
             (IC -113.4%) with portable 0-1 normalized signal.
             Expected frequency = ~40-50 trades/year.

  Pathway 5: Regime trending_down -> adxr(period) > adxr_threshold              -> LONG
             IC = +0.277 (STRONG), asymmetric positive tail (0.610),
             strong trend direction supports LONG momentum entry.
             Expected frequency = ~15-20 trades/year.
             PRESERVED: Historical precedent v3.5/v3.6 — disabling caused OOS collapse.

  Pathway 6: Regime trending_down -> ad > ad_threshold                          -> SHORT
             IC = -0.356 (STRONG), Pos tail IC -0.496,
             high Chaikin A/D accumulation predicts decline in negative-drift
             regime. Expected frequency = ~3.6 signals/year (11.53% × 31.5 days).
             Evaluated only when Pathway 5 not triggered.

Entry timing: At next bar open (T+1 execution delay per framework constraints).
No confirmation filter applied (baseline simplicity per complexity budget).
"""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import (
    ITradingEngine,
    OrderIntent,
)
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    """
    Multi-regime entry component for SHFE aluminum daily bars.

    Implements six momentum-aligned entry pathways covering all market regimes:
    - TRENDING_UP regime LONG entries via CCI oscillator
      (IC=+0.215: high CCI predicts continued upward momentum)
    - VOLATILE regime SHORT entries via OBV accumulation/distribution
      (IC=-0.528: high OBV predicts lower future returns in volatile regime)
    - RANGING regime LONG entries via MACD histogram
      (IC=+0.206: positive histogram shift predicts mean-reversion bounce)
    - RANGING regime SHORT entries via BBands %B mean-reversion
      (IC=+0.148: high %B price near upper band predicts mean-reversion SHORT)
    - TRENDING_DOWN regime LONG entries via ADXR momentum
      (IC=+0.277 STRONG: asymmetric positive tail validates LONG on high ADXR)
      PRESERVED: v3.5/v3.6 historical OOS collapse precedent — must not disable
    - TRENDING_DOWN regime SHORT entries via Chaikin A/D Line
      (IC=-0.356 STRONG: high accumulation predicts decline in negative-drift regime)

    Market regime classification is framework-provided (SMA+ADX methodology).
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Indicator periods
        self.cci_period = self.params['cci_period']
        self.adxr_period = self.params['adxr_period']

        # Entry thresholds
        self.cci_threshold = self.params['cci_threshold']
        self.obv_threshold = self.params['obv_threshold']
        self.macd_histogram_threshold = self.params['macd_histogram_threshold']
        self.bbands_pct_b_short_threshold = self.params['bbands_pct_b_short_threshold']
        self.adxr_threshold = self.params['adxr_threshold']
        self.ad_threshold = self.params['ad_threshold']

    def generate_signal(self) -> EntrySignalOutput:
        """
        Generate entry signal based on six-pathway regime-momentum logic.

        Pathway 1 (trending_up LONG):
            IF market_regime == 'trending_up' AND cci(period) > cci_threshold
            THEN signal = LONG
            Rationale: CCI IC=+0.215, high values predict momentum continuation.

        Pathway 2 (volatile SHORT):
            IF market_regime == 'volatile' AND obv > obv_threshold
            THEN signal = SHORT
            Rationale: OBV IC=-0.528, high accumulation predicts lower returns
            in downtrend-skewed volatile regime.

        Pathway 3 (ranging LONG):
            IF market_regime == 'ranging' AND macd_histogram > macd_histogram_threshold
            THEN signal = LONG
            Rationale: MACD histogram IC=+0.206, positive shift predicts
            mean-reversion bounce in ranging conditions.

        Pathway 4 (ranging SHORT):
            IF market_regime == 'ranging' AND bbands_pct_b > bbands_pct_b_short_threshold
            THEN signal = SHORT (evaluated only when Pathway 3 not triggered)
            Rationale: BBands %B IC=+0.148, high %B (price near upper band)
            predicts mean-reversion SHORT in ranging regime.

        Pathway 5 (trending_down LONG):
            IF market_regime == 'trending_down' AND adxr(period) > adxr_threshold
            THEN signal = LONG
            Rationale: ADXR IC=+0.277 STRONG, asymmetric positive tail (0.610),
            strong trend direction supports LONG momentum entry.
            PRESERVED: v3.5 direction flip caused DRS 44.3->0.0; v3.6 disable
            caused G1 OOS failure. Checked FIRST before Pathway 6.

        Pathway 6 (trending_down SHORT):
            IF market_regime == 'trending_down' AND ad > ad_threshold
            THEN signal = SHORT (evaluated only when Pathway 5 not triggered)
            Rationale: AD IC=-0.356 STRONG, Pos tail IC=-0.496. High Chaikin
            A/D accumulation in negative-drift regime predicts decline.
            Expected frequency ~3.6 signals/year.

        All other conditions (unmet thresholds) → HOLD.

        Returns:
            EntrySignalOutput with signal, strength, type, entry_reason, intent,
            regime, cci_value, obv_value, macd_histogram_value, bbands_pct_b_value,
            adxr_value, ad_value diagnostics.
        """
        # Get market regime via interday infrastructure method
        regime = self.get_market_regime()

        # Tier 1: CCI with period (trending_up pathway)
        cci = self.get_indicator(f'cci_{self.cci_period}')

        # Tier 3: OBV without lookback (volatile pathway)
        obv = self.get_indicator('obv')

        # Tier 2: MACD histogram with special params (ranging LONG pathway)
        macd_histogram = self.get_indicator('macd_histogram')

        # Tier 2: BBands %B with special params (ranging SHORT pathway)
        # Design decision: bbands_pct_b is Tier 2 — uses ta_lib.py defaults (period=20, dev=2.0).
        # bbands_period / bbands_dev are NOT in EntryParameters or Optuna search space because
        # Tier 2 indicators do not accept custom lookback periods via the standard mechanism.
        # Per params_to_optimize.json extraction_report: "Removed 2 invalid Tier 2 calculation
        # params (bbands_period, bbands_dev) - bbands_pct_b uses ta_lib defaults." Intentional.
        bbands_pct_b = self.get_indicator('bbands_pct_b')

        # Tier 1: ADXR with period (trending_down LONG pathway)
        adxr = self.get_indicator(f'adxr_{self.adxr_period}')

        # Tier 3: Chaikin A/D Line without lookback (trending_down SHORT pathway)
        ad = self.get_indicator('ad')

        # Initialize defaults
        signal = 'HOLD'
        intent = None
        strength = 0.0
        signal_type = 'hold'
        reason = ''

        # Pathway 1: TRENDING_UP regime — LONG via CCI momentum continuation
        if regime == 'trending_up':
            if cci > self.cci_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                signal_type = 'entry_long'
                # Strength: normalized CCI excess above threshold (IC=+0.215 momentum)
                cci_excess = cci - self.cci_threshold
                strength = min(1.0, cci_excess / max(1.0, self.cci_threshold))
                reason = (
                    f'Trending Up regime: CCI({self.cci_period}) {cci:.2f} > threshold '
                    f'{self.cci_threshold:.1f} - momentum continuation LONG '
                    f'(IC=+0.215, signal_freq=11.79%)'
                )
            else:
                reason = (
                    f'Trending Up regime: CCI({self.cci_period}) {cci:.2f} <= threshold '
                    f'{self.cci_threshold:.1f} - no LONG entry condition met'
                )

        # Pathway 2: VOLATILE regime — SHORT via OBV divergence
        elif regime == 'volatile':
            if obv > self.obv_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                signal_type = 'entry_short'
                # Strength: normalized OBV excess above threshold (IC=-0.528 negative momentum)
                # High OBV in volatile regime predicts lower returns (negative IC)
                obv_excess = obv - self.obv_threshold
                denom = max(1.0, abs(self.obv_threshold))
                strength = min(1.0, obv_excess / denom)
                reason = (
                    f'Volatile regime: OBV {obv:.0f} > threshold {self.obv_threshold:.0f} '
                    f'- high accumulation predicts lower returns SHORT entry '
                    f'(IC=-0.528, signal_freq=12.10%)'
                )
            else:
                reason = (
                    f'Volatile regime: OBV {obv:.0f} <= threshold {self.obv_threshold:.0f} '
                    f'- no SHORT entry condition met'
                )

        # Pathways 3 & 4: RANGING regime — bidirectional mean-reversion entries
        elif regime == 'ranging':
            # Pathway 3: RANGING LONG via MACD histogram momentum bounce
            if macd_histogram > self.macd_histogram_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                signal_type = 'entry_long'
                # Strength: normalized MACD histogram excess above threshold (IC=+0.206)
                macd_excess = macd_histogram - self.macd_histogram_threshold
                # denom = max(1.0, abs(threshold)); threshold range [-0.06, -0.03] never zero.
                denom = max(1.0, abs(self.macd_histogram_threshold))
                strength = min(1.0, macd_excess / denom)
                reason = (
                    f'Ranging regime: MACD histogram {macd_histogram:.4f} > threshold '
                    f'{self.macd_histogram_threshold:.4f} - mean-reversion bounce LONG entry '
                    f'(IC=+0.206, signal_freq=10.14%)'
                )
            # Pathway 4: RANGING SHORT via BBands %B mean-reversion
            elif bbands_pct_b > self.bbands_pct_b_short_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                signal_type = 'entry_short'
                # Strength: normalized %B excess above threshold (IC=+0.148)
                # %B is 0-1 normalized; denominator = distance from threshold to 1.0
                pct_b_excess = bbands_pct_b - self.bbands_pct_b_short_threshold
                denom = max(0.1, 1.0 - self.bbands_pct_b_short_threshold)
                strength = min(1.0, pct_b_excess / denom)
                reason = (
                    f'Ranging regime: BBands %B {bbands_pct_b:.4f} > threshold '
                    f'{self.bbands_pct_b_short_threshold:.2f} - price near upper band '
                    f'mean-reversion SHORT entry (IC=+0.148)'
                )
            else:
                reason = (
                    f'Ranging regime: MACD histogram {macd_histogram:.4f} <= threshold '
                    f'{self.macd_histogram_threshold:.4f} AND '
                    f'BBands %B {bbands_pct_b:.4f} <= threshold '
                    f'{self.bbands_pct_b_short_threshold:.2f} - no entry condition met'
                )

        # Pathways 5 & 6: TRENDING_DOWN regime — LONG via ADXR (preserved), SHORT via AD (new)
        elif regime == 'trending_down':
            # Pathway 5: TRENDING_DOWN LONG via ADXR momentum (PRESERVED per v3.5/v3.6 mandate)
            if adxr > self.adxr_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                signal_type = 'entry_long'
                # Strength: normalized ADXR excess above threshold (IC=+0.277 asymmetric positive)
                adxr_excess = adxr - self.adxr_threshold
                strength = min(1.0, adxr_excess / max(1.0, self.adxr_threshold))
                reason = (
                    f'Trending Down regime: ADXR({self.adxr_period}) {adxr:.2f} > threshold '
                    f'{self.adxr_threshold:.1f} - strong trend direction LONG entry '
                    f'(IC=+0.277 STRONG, asymmetric positive tail 0.610)'
                )
            # Pathway 6: TRENDING_DOWN SHORT via Chaikin A/D Line (new pathway)
            elif ad > self.ad_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                signal_type = 'entry_short'
                # Strength: normalized AD excess above threshold (IC=-0.356 STRONG negative)
                # High A/D accumulation in negative-drift regime predicts decline
                ad_excess = ad - self.ad_threshold
                denom = max(1.0, abs(self.ad_threshold))
                strength = min(1.0, ad_excess / denom)
                reason = (
                    f'Trending Down regime: AD {ad:.0f} > threshold {self.ad_threshold:.0f} '
                    f'- high A/D accumulation predicts decline SHORT entry '
                    f'(IC=-0.356 STRONG, Pos tail IC=-0.496, ~3.6 signals/year)'
                )
            else:
                reason = (
                    f'Trending Down regime: ADXR({self.adxr_period}) {adxr:.2f} <= threshold '
                    f'{self.adxr_threshold:.1f} AND '
                    f'AD {ad:.0f} <= threshold {self.ad_threshold:.0f} '
                    f'- no entry condition met'
                )

        # Unknown regime — no entry signal
        else:
            reason = (
                f'Unknown regime: {regime} '
                f'(active regimes: trending_up, volatile, ranging, trending_down). '
                f'CCI({self.cci_period})={cci:.2f}, OBV={obv:.0f} - HOLD'
            )

        output = EntrySignalOutput(
            signal=signal,
            strength=strength,
            type=signal_type,
            entry_reason=reason,
            intent=intent,
            regime=regime,
            cci_value=cci,
            obv_value=obv,
            macd_histogram_value=macd_histogram,
            bbands_pct_b_value=bbands_pct_b,
            adxr_value=adxr,
            ad_value=ad,
        )

        self.log_entry_output(output)
        return output
