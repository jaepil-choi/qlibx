"""
Strategy Parameters — fixture for echolon's preflight / validator / structure
tests. Equivalent in shape to what ``echolon.strategy.generators.generate_strategy_params``
emits from a hand-curated ``params_to_optimize.json``.
"""

from typing import List, Dict, Any
import optuna
from echolon.strategy.parameter_architecture import (
    ComponentParameterTemplate,
    ParameterSpec,
    ParameterType,
    StrategyParameterFramework
)



class EntryParameters(ComponentParameterTemplate):
    """Parameter definitions for entry component"""

    def get_component_name(self) -> str:
        return 'entry'

    def define_parameters(self) -> List[ParameterSpec]:
        return [
        ParameterSpec(
            name="cci_period",
            param_type=ParameterType.INT,
            default_value=11,
            min_value=10,
            max_value=13,
            description="Commodity Channel Index lookback period for trending_up LONG momentum signals"
        ),
        ParameterSpec(
            name="adxr_period",
            param_type=ParameterType.INT,
            default_value=14,
            min_value=13,
            max_value=16,
            description="Average Directional Movement Index Rating period for trending_down LONG signals"
        ),
        ParameterSpec(
            name="cci_threshold",
            param_type=ParameterType.FLOAT,
            default_value=52.5,
            min_value=45.0,
            max_value=60.0,
            description="CCI LONG entry threshold - trade when cci > threshold in trending_up regime"
        ),
        ParameterSpec(
            name="obv_threshold",
            param_type=ParameterType.FLOAT,
            default_value=900000.0,
            min_value=600000.0,
            max_value=1200000.0,
            description="OBV threshold for volatile SHORT signals - trade when obv > threshold"
        ),
        ParameterSpec(
            name="macd_histogram_threshold",
            param_type=ParameterType.FLOAT,
            default_value=0.002,
            min_value=0.001,
            max_value=0.003,
            description="MACD histogram LONG threshold for ranging regime mean-reversion"
        ),
        ParameterSpec(
            name="bbands_pct_b_short_threshold",
            param_type=ParameterType.FLOAT,
            default_value=0.725,
            min_value=0.7,
            max_value=0.75,
            description="Bollinger Bands %B SHORT threshold - trade when %B > threshold in ranging regime"
        ),
        ParameterSpec(
            name="adxr_threshold",
            param_type=ParameterType.FLOAT,
            default_value=29.5,
            min_value=27.0,
            max_value=32.0,
            description="ADXR threshold for trending_down LONG - trade when adxr > threshold"
        ),
        ParameterSpec(
            name="ad_threshold",
            param_type=ParameterType.FLOAT,
            default_value=325000.0,
            min_value=150000.0,
            max_value=500000.0,
            description="Chaikin A/D Line SHORT threshold for trending_down regime - trade SHORT when ad > threshold (high accumulation predicts decline in negative drift regime)"
        )
        ]



class ExitParameters(ComponentParameterTemplate):
    """Parameter definitions for exit component"""

    def get_component_name(self) -> str:
        return 'exit'

    def define_parameters(self) -> List[ParameterSpec]:
        return [
        ParameterSpec(
            name="atr_period",
            param_type=ParameterType.INT,
            default_value=17,
            min_value=15,
            max_value=19,
            description="ATR lookback period for trailing stop distance and MFE range calculation, preserved from v5.6 WFA-optimized lock"
        ),
        ParameterSpec(
            name="mfe_lookback_window",
            param_type=ParameterType.INT,
            default_value=16,
            min_value=15,
            max_value=18,
            description="Lookback window for calculating recent price range for MFE profit target baseline"
        ),
        ParameterSpec(
            name="profit_capture_trending_down_short_pct",
            param_type=ParameterType.FLOAT,
            default_value=0.85,
            min_value=0.8,
            max_value=0.9,
            description="MFE profit capture percentage for trending_down SHORT signals - aggressive 0.85 capture for strong IC -0.356 trend momentum, higher than standard 0.78"
        ),
        ParameterSpec(
            name="max_holding_trending_short_bars",
            param_type=ParameterType.INT,
            default_value=18,
            min_value=15,
            max_value=22,
            description="Maximum holding period for trending_down SHORT - shorter than LONG counterpart (18 vs 25) reflecting faster exhaustion of short momentum in negative drift regime"
        ),
        ParameterSpec(
            name="profit_capture_pct",
            param_type=ParameterType.FLOAT,
            default_value=0.78,
            min_value=0.7,
            max_value=0.85,
            description="Base MFE profit capture percentage for standard trend-following LONG pathways"
        ),
        ParameterSpec(
            name="max_holding_trending_bars",
            param_type=ParameterType.INT,
            default_value=25,
            min_value=20,
            max_value=30,
            description="Maximum holding period for trending trend-following LONG pathways (trending_up LONG, trending_down LONG)"
        ),
        ParameterSpec(
            name="atr_multiplier_trending_up",
            param_type=ParameterType.FIXED,
            default_value=2.357383,
            description="ATR multiplier for trending_up LONG trailing stop - FIXED per protective mechanism mandate"
        ),
        ParameterSpec(
            name="atr_multiplier_volatile",
            param_type=ParameterType.FIXED,
            default_value=3.215562,
            description="ATR multiplier for volatile SHORT trailing stop - FIXED per protective mechanism mandate"
        ),
        ParameterSpec(
            name="atr_multiplier_ranging_long",
            param_type=ParameterType.FIXED,
            default_value=2.172573,
            description="ATR multiplier for ranging LONG trailing stop - FIXED per protective mechanism mandate"
        ),
        ParameterSpec(
            name="atr_multiplier_ranging_short",
            param_type=ParameterType.FIXED,
            default_value=2.3255,
            description="ATR multiplier for ranging SHORT trailing stop - FIXED per protective mechanism mandate"
        ),
        ParameterSpec(
            name="atr_multiplier_trending_down",
            param_type=ParameterType.FIXED,
            default_value=2.610751,
            description="ATR multiplier for trending_down LONG trailing stop - FIXED per protective mechanism mandate"
        ),
        ParameterSpec(
            name="atr_multiplier_trending_down_short",
            param_type=ParameterType.FIXED,
            default_value=2.8,
            description="ATR multiplier for trending_down SHORT trailing stop - FIXED at 2.8 (wider than LONG 2.61) for highest regime volatility 17.61%, prevents premature stop-outs on volatile SHORT entries"
        ),
        ParameterSpec(
            name="max_holding_standard_bars",
            param_type=ParameterType.FIXED,
            default_value=20,
            description="Maximum holding period for ranging/volatile regimes (mean-reversion and divergence signals) - FIXED per baseline"
        )
        ]



class RiskParameters(ComponentParameterTemplate):
    """Parameter definitions for risk component"""

    def get_component_name(self) -> str:
        return 'risk'

    def define_parameters(self) -> List[ParameterSpec]:
        return [
        ParameterSpec(
            name="max_drawdown_pct",
            param_type=ParameterType.FLOAT,
            default_value=6.5,
            min_value=6.0,
            max_value=7.0,
            description="Drawdown circuit breaker threshold - binary halt trigger when current drawdown percentage from equity peak exceeds this value (6.5% default, optimized anchor ~6.36%)"
        ),
        ParameterSpec(
            name="max_capital_deployed_pct",
            param_type=ParameterType.FLOAT,
            default_value=100.0,
            min_value=80.0,
            max_value=100.0,
            description="Maximum percentage of total capital that may be deployed in open positions at any time"
        ),
        ParameterSpec(
            name="max_concurrent_positions",
            param_type=ParameterType.FIXED,
            default_value=1,
            description="Maximum number of concurrent positions allowed - structural constraint enforced by strategy flow architecture (single-position limit)"
        )
        ]



class SizerParameters(ComponentParameterTemplate):
    """Parameter definitions for sizer component"""

    def get_component_name(self) -> str:
        return 'sizer'

    def define_parameters(self) -> List[ParameterSpec]:
        return [
        ParameterSpec(
            name="atr_period",
            param_type=ParameterType.INT,
            default_value=17,
            min_value=15,
            max_value=19,
            description="ATR lookback period for position size denominator calculation - shared from exit component [SHARED with: exit]"
        ),
        ParameterSpec(
            name="default_risk_per_trade_pct",
            param_type=ParameterType.FLOAT,
            default_value=4.5,
            min_value=4.0,
            max_value=5.0,
            description="Default risk percentage per trade for non-volatile regimes (trending_up, trending_down, ranging). Range floor aligns with break_even_at_median (4.57%), ensuring marginal rounding rescue maintains execution."
        ),
        ParameterSpec(
            name="volatile_regime_risk_per_trade_pct",
            param_type=ParameterType.FLOAT,
            default_value=5.3,
            min_value=5.05,
            max_value=6.0,
            description="Elevated risk percentage for volatile regime matching wider ATR stops (3.59x vs ~2.5x trending) to maintain consistent nominal risk exposure per trade."
        ),
        ParameterSpec(
            name="marginal_rounding_threshold",
            param_type=ParameterType.FLOAT,
            default_value=0.5,
            min_value=0.3,
            max_value=0.7,
            description="Rescue threshold for sub-1-lot positions - when raw_size >= threshold AND raw_size < 1.0, rounds UP to 1 lot. Required per PARAMETER_RULES_CONTEXT Rule 5 for futures with contract_multiplier > 1. Prevents starvation from conservative sizing calculations."
        ),
        ParameterSpec(
            name="max_position_lots",
            param_type=ParameterType.FIXED,
            default_value=1,
            description="Maximum position size in lots - HARD CONSTRAINT, framework infrastructure limitation (not adjustable via strategy exploration). Enforced by validate_position_size() infrastructure."
        ),
        ParameterSpec(
            name="contract_multiplier",
            param_type=ParameterType.FIXED,
            default_value=5,
            description="SHFE aluminum futures contract multiplier (5 metric tons per lot) - structural exchange parameter."
        ),
        ParameterSpec(
            name="trailing_atr_multiplier_trending_up",
            param_type=ParameterType.FIXED,
            default_value=2.507365447069778,
            description="ATR multiplier for trending_up LONG position sizing denominator. FIXED - per baseline_param_classifications and v5.6 stability pattern. Shared from exit component logic alignment."
        ),
        ParameterSpec(
            name="trailing_atr_multiplier_volatile",
            param_type=ParameterType.FIXED,
            default_value=3.590769399256032,
            description="ATR multiplier for volatile SHORT position sizing denominator. FIXED - per baseline_param_classifications. Shared from exit component logic alignment."
        ),
        ParameterSpec(
            name="trailing_atr_multiplier_ranging_long",
            param_type=ParameterType.FIXED,
            default_value=2.3048729881608385,
            description="ATR multiplier for ranging LONG position sizing denominator. FIXED - per baseline_param_classifications. Shared from exit component logic alignment."
        ),
        ParameterSpec(
            name="trailing_atr_multiplier_ranging_short",
            param_type=ParameterType.FIXED,
            default_value=2.118024386610257,
            description="ATR multiplier for ranging SHORT position sizing denominator. FIXED - per baseline_param_classifications. Shared from exit component logic alignment."
        ),
        ParameterSpec(
            name="trailing_atr_multiplier_trending_down",
            param_type=ParameterType.FIXED,
            default_value=2.455981830181817,
            description="ATR multiplier for trending_down LONG position sizing denominator. FIXED - per baseline_param_classifications. Shared from exit component logic alignment."
        ),
        ParameterSpec(
            name="trailing_atr_multiplier_trending_down_short",
            param_type=ParameterType.FIXED,
            default_value=2.8,
            description="ATR multiplier for trending_down SHORT position sizing denominator - aligned with exit_logic_upstream atr_multiplier_trending_down_short=2.8 (wider stop for highest volatility regime), ensures sizing consistency with new pathway exit architecture. Shared from exit component logic alignment."
        )
        ]



# Initialize framework and register components
framework = StrategyParameterFramework()
framework.register_component(EntryParameters())
framework.register_component(ExitParameters())
framework.register_component(RiskParameters())
framework.register_component(SizerParameters())

# Generate default parameter structure
DEFAULT_PARAMS = framework.compose_default_strategy()

# Add shared parameters: copy from owner components
DEFAULT_PARAMS['sizer_params']['atr_period'] = DEFAULT_PARAMS['exit_params']['atr_period']



def get_shared_params_mapping() -> Dict[str, Dict[str, Any]]:
    """
    Returns the mapping of shared parameters between components.

    This function is AUTO-GENERATED based on params_to_optimize.json ownership.
    Used by select_best_trial.py to apply optimized values from owner to shared params.

    Returns:
        Dict mapping param_name to {'owner': component_name, 'owner_param': owner_param_name, 'shared_by': [component_names]}
    """
    return {
        "atr_period": {"owner": "exit", "owner_param": "atr_period", "shared_by": ['sizer']},
    }


def apply_shared_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply shared parameter values from owner components to all shared components.

    This function is AUTO-GENERATED. It copies optimized parameter values from
    the owner component to all components that share that parameter.

    Handles differently-named shared parameters (e.g., exit_atr_period → sizer_atr_period).

    Args:
        params: Parameter dict with keys like 'component_paramname' (e.g., 'exit_atr_period')

    Returns:
        Updated params dict with shared params filled from owner's values
    """
    shared_mapping = get_shared_params_mapping()

    for param_name, info in shared_mapping.items():
        owner_param = info['owner_param']

        if owner_param in params:
            source_value = params[owner_param]
            params[param_name] = source_value

    return params



def optuna_search_space(trial: optuna.Trial) -> Dict[str, Any]:
    """
    Generate parameter search space for Optuna optimization.

    This function is AUTO-GENERATED with crossover constraints to prevent
    identical period values that cause zero-trade scenarios.
    """
    params = {}

    # Component parameters

    # Entry parameters
    entry_params = {}
    entry_params["cci_period"] = trial.suggest_int("entry_cci_period", 10, 13)
    entry_params["adxr_period"] = trial.suggest_int("entry_adxr_period", 13, 16)
    entry_params["cci_threshold"] = trial.suggest_float("entry_cci_threshold", 45.0, 60.0)
    entry_params["obv_threshold"] = trial.suggest_float("entry_obv_threshold", 600000.0, 1200000.0)
    entry_params["macd_histogram_threshold"] = trial.suggest_float("entry_macd_histogram_threshold", 0.001, 0.003)
    entry_params["bbands_pct_b_short_threshold"] = trial.suggest_float("entry_bbands_pct_b_short_threshold", 0.7, 0.75)
    entry_params["adxr_threshold"] = trial.suggest_float("entry_adxr_threshold", 27.0, 32.0)
    entry_params["ad_threshold"] = trial.suggest_float("entry_ad_threshold", 150000.0, 500000.0)
    params["entry_params"] = entry_params

    # Exit parameters
    exit_params = {}
    exit_params["atr_period"] = trial.suggest_int("exit_atr_period", 15, 19)
    exit_params["mfe_lookback_window"] = trial.suggest_int("exit_mfe_lookback_window", 15, 18)
    exit_params["profit_capture_trending_down_short_pct"] = trial.suggest_float("exit_profit_capture_trending_down_short_pct", 0.8, 0.9)
    exit_params["max_holding_trending_short_bars"] = trial.suggest_int("exit_max_holding_trending_short_bars", 15, 22)
    exit_params["profit_capture_pct"] = trial.suggest_float("exit_profit_capture_pct", 0.7, 0.85)
    exit_params["max_holding_trending_bars"] = trial.suggest_int("exit_max_holding_trending_bars", 20, 30)
    exit_params["atr_multiplier_trending_up"] = 2.357383
    exit_params["atr_multiplier_volatile"] = 3.215562
    exit_params["atr_multiplier_ranging_long"] = 2.172573
    exit_params["atr_multiplier_ranging_short"] = 2.3255
    exit_params["atr_multiplier_trending_down"] = 2.610751
    exit_params["atr_multiplier_trending_down_short"] = 2.8
    exit_params["max_holding_standard_bars"] = 20
    params["exit_params"] = exit_params

    # Risk parameters
    risk_params = {}
    risk_params["max_drawdown_pct"] = trial.suggest_float("risk_max_drawdown_pct", 6.0, 7.0)
    risk_params["max_capital_deployed_pct"] = trial.suggest_float("risk_max_capital_deployed_pct", 80.0, 100.0)
    risk_params["max_concurrent_positions"] = 1
    params["risk_params"] = risk_params

    # Sizer parameters
    sizer_params = {}
    # Shared parameter from exit
    sizer_params["atr_period"] = exit_params["atr_period"]
    sizer_params["default_risk_per_trade_pct"] = trial.suggest_float("sizer_default_risk_per_trade_pct", 4.0, 5.0)
    sizer_params["volatile_regime_risk_per_trade_pct"] = trial.suggest_float("sizer_volatile_regime_risk_per_trade_pct", 5.05, 6.0)
    sizer_params["marginal_rounding_threshold"] = trial.suggest_float("sizer_marginal_rounding_threshold", 0.3, 0.7)
    sizer_params["max_position_lots"] = 1
    sizer_params["contract_multiplier"] = 5
    sizer_params["trailing_atr_multiplier_trending_up"] = 2.507365447069778
    sizer_params["trailing_atr_multiplier_volatile"] = 3.590769399256032
    sizer_params["trailing_atr_multiplier_ranging_long"] = 2.3048729881608385
    sizer_params["trailing_atr_multiplier_ranging_short"] = 2.118024386610257
    sizer_params["trailing_atr_multiplier_trending_down"] = 2.455981830181817
    sizer_params["trailing_atr_multiplier_trending_down_short"] = 2.8
    params["sizer_params"] = sizer_params

    # Framework requirement
    params["entry_params"]["printlog"] = False
    params["exit_params"]["printlog"] = False
    params["risk_params"]["printlog"] = False
    params["sizer_params"]["printlog"] = False

    return params
