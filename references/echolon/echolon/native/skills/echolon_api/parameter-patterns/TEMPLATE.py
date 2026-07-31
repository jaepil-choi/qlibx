"""
Parameter Template for Strategy Development

This template shows the standard pattern for strategy_params.py.
Copy and modify for new strategies.
"""
from typing import List, Dict, Any, Optional
import optuna

from ..core.parameter_architecture import (
    ComponentParameterTemplate,
    ParameterSpec,
    ParameterType,
    StrategyParameterFramework
)


# ==============================================================================
# ENTRY PARAMETERS
# ==============================================================================
class EntryParameters(ComponentParameterTemplate):
    """Entry parameter definitions."""

    def get_component_name(self) -> str:
        return "entry"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            # Calculation parameters (owned by Entry)
            ParameterSpec(
                name="adx_period",
                param_type=ParameterType.INT,
                default_value=14,
                min_value=10,
                max_value=93,  # ADX cap
                description="ADX calculation period [SHARED with: exit, risk, sizer]"
            ),
            ParameterSpec(
                name="rsi_period",
                param_type=ParameterType.INT,
                default_value=14,
                min_value=7,
                max_value=21,
                description="RSI calculation period"
            ),
            # Usage parameters (Entry-specific)
            ParameterSpec(
                name="adx_threshold",
                param_type=ParameterType.FLOAT,
                default_value=25.0,
                min_value=20.0,
                max_value=35.0,
                description="ADX threshold for trending regime"
            ),
            ParameterSpec(
                name="rsi_oversold",
                param_type=ParameterType.FLOAT,
                default_value=30.0,
                min_value=20.0,
                max_value=40.0,
                description="RSI oversold threshold"
            ),
        ]


# ==============================================================================
# EXIT PARAMETERS
# ==============================================================================
class ExitParameters(ComponentParameterTemplate):
    """Exit parameter definitions."""

    def get_component_name(self) -> str:
        return "exit"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            # Calculation parameters (owned by Exit)
            ParameterSpec(
                name="atr_period",
                param_type=ParameterType.INT,
                default_value=14,
                min_value=10,
                max_value=21,
                description="ATR calculation period [SHARED with: risk, sizer]"
            ),
            # Usage parameters (Exit-specific)
            ParameterSpec(
                name="atr_stop_multiplier",
                param_type=ParameterType.FLOAT,
                default_value=2.0,
                min_value=1.5,
                max_value=3.5,
                description="ATR multiplier for stop loss"
            ),
        ]


# ==============================================================================
# RISK PARAMETERS
# ==============================================================================
class RiskParameters(ComponentParameterTemplate):
    """Risk parameter definitions."""

    def get_component_name(self) -> str:
        return "risk"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            # Usage parameters (Risk-specific)
            ParameterSpec(
                name="max_drawdown",
                param_type=ParameterType.FLOAT,
                default_value=0.10,
                min_value=0.05,
                max_value=0.20,
                description="Maximum portfolio drawdown"
            ),
            ParameterSpec(
                name="adx_min_threshold",
                param_type=ParameterType.FLOAT,
                default_value=15.0,
                min_value=10.0,
                max_value=25.0,
                description="Minimum ADX for trading"
            ),
        ]


# ==============================================================================
# SIZER PARAMETERS
# ==============================================================================
class SizerParameters(ComponentParameterTemplate):
    """Sizer parameter definitions."""

    def get_component_name(self) -> str:
        return "sizer"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            # Usage parameters (Sizer-specific)
            ParameterSpec(
                name="risk_per_trade",
                param_type=ParameterType.FLOAT,
                default_value=0.02,
                min_value=0.01,
                max_value=0.05,
                description="Risk per trade as portfolio fraction"
            ),
            ParameterSpec(
                name="max_position_pct",
                param_type=ParameterType.FLOAT,
                default_value=0.30,
                min_value=0.10,
                max_value=0.50,
                description="Maximum position as portfolio fraction"
            ),
        ]


# ==============================================================================
# FRAMEWORK SETUP
# ==============================================================================
def create_strategy_framework() -> StrategyParameterFramework:
    """Create and configure the parameter framework."""
    framework = StrategyParameterFramework()

    # Register all components
    framework.register_component(EntryParameters())
    framework.register_component(ExitParameters())
    framework.register_component(RiskParameters())
    framework.register_component(SizerParameters())

    # Strategy-level parameters (optional)
    framework.define_strategy_level_parameters([
        ParameterSpec(
            name="allow_reentry_on_same_bar_after_exit",
            param_type=ParameterType.CATEGORICAL,
            default_value=False,
            choices=[True, False]
        )
    ])

    return framework


# ==============================================================================
# EXPORTS
# ==============================================================================
_framework = create_strategy_framework()
DEFAULT_PARAMS = _framework.compose_default_strategy()


def optuna_search_space(trial: optuna.Trial) -> Dict[str, Any]:
    """Generate Optuna parameter search space."""
    params = {}

    # Entry parameters
    entry_params = {}
    entry_params["adx_period"] = trial.suggest_int("entry_adx_period", 10, 93)
    entry_params["rsi_period"] = trial.suggest_int("entry_rsi_period", 7, 21)
    entry_params["adx_threshold"] = trial.suggest_float("entry_adx_threshold", 20.0, 35.0)
    entry_params["rsi_oversold"] = trial.suggest_float("entry_rsi_oversold", 20.0, 40.0)
    entry_params["printlog"] = False
    params["entry_params"] = entry_params

    # Exit parameters
    exit_params = {}
    exit_params["atr_period"] = trial.suggest_int("exit_atr_period", 10, 21)
    exit_params["atr_stop_multiplier"] = trial.suggest_float("exit_atr_stop_multiplier", 1.5, 3.5)
    exit_params["printlog"] = False
    params["exit_params"] = exit_params

    # Risk parameters
    risk_params = {}
    risk_params["max_drawdown"] = trial.suggest_float("risk_max_drawdown", 0.05, 0.20)
    risk_params["adx_min_threshold"] = trial.suggest_float("risk_adx_min_threshold", 10.0, 25.0)
    risk_params["printlog"] = False
    params["risk_params"] = risk_params

    # Sizer parameters
    sizer_params = {}
    sizer_params["risk_per_trade"] = trial.suggest_float("sizer_risk_per_trade", 0.01, 0.05)
    sizer_params["max_position_pct"] = trial.suggest_float("sizer_max_position_pct", 0.10, 0.50)
    sizer_params["printlog"] = False
    params["sizer_params"] = sizer_params

    # CROSSOVER CONSTRAINTS (if applicable)
    # Example for TEMA short/long:
    # if entry_params.get("tema_long_period", 0) <= entry_params.get("tema_short_period", 0) + 5:
    #     raise optuna.TrialPruned()

    return params
