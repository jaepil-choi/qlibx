# Parameter Patterns Examples

## Parameter Ownership Rules

### Ownership Priority
```
Entry → Exit → Risk → Sizer
```

When a calculation parameter is shared across components:
1. Find the first component in the priority order that uses it
2. That component OWNS the parameter
3. Other components reference it but don't include it in `define_parameters()`

### Example: ADX Period Shared

From `params_to_optimize.md`:
```json
{
  "entry_parameters": {
    "calculation": {
      "adx_period": {
        "description": "ADX period SHARED by Entry, Exit, Risk, Sizing"
      }
    }
  }
}
```

**Correct Implementation:**

```python
# Entry OWNS adx_period (first in priority)
class EntryParameters(ComponentParameterTemplate):
    def define_parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec(
                name="adx_period",  # OWNER
                param_type=ParameterType.INT,
                default_value=14,
                min_value=10,
                max_value=93,
                description="ADX period [SHARED with: exit, risk, sizer]"
            ),
        ]

# Exit does NOT include adx_period
class ExitParameters(ComponentParameterTemplate):
    def define_parameters(self) -> List[ParameterSpec]:
        return [
            # NO adx_period here - Entry owns it
            ParameterSpec(
                name="atr_period",  # Exit can own different params
                param_type=ParameterType.INT,
                default_value=14,
                min_value=10,
                max_value=21,
                description="ATR period [SHARED with: risk, sizer]"
            ),
        ]
```

## Crossover Constraints

For parameters that must maintain order (short < long, fast < slow):

```python
def optuna_search_space(trial: optuna.Trial) -> Dict[str, Any]:
    params = {}
    entry_params = {}

    # TEMA crossover example
    tema_short = trial.suggest_int("entry_tema_short_period", 10, 55)
    tema_long = trial.suggest_int("entry_tema_long_period", 20, 62)

    # MANDATORY: Enforce crossover constraint
    if tema_long <= tema_short + 5:
        raise optuna.TrialPruned()

    entry_params["tema_short_period"] = tema_short
    entry_params["tema_long_period"] = tema_long

    # EMA crossover example
    ema_fast = trial.suggest_int("entry_ema_fast_period", 5, 20)
    ema_slow = trial.suggest_int("entry_ema_slow_period", 15, 50)

    if ema_slow <= ema_fast + 3:
        raise optuna.TrialPruned()

    entry_params["ema_fast_period"] = ema_fast
    entry_params["ema_slow_period"] = ema_slow

    entry_params["printlog"] = False
    params["entry_params"] = entry_params
    return params
```

## Indicator Period Caps

Always respect indicator-specific maximum periods:

| Indicator Type | Maximum Period | Reason |
|----------------|----------------|--------|
| TEMA, TRIX, ADXR | 62 | Triple smoothing causes NaN |
| ADX, DEMA | 93 | Double smoothing causes NaN |
| Standard (RSI, ATR, EMA, etc.) | 180 | Data availability |

```python
# CORRECT: Respects TEMA cap
ParameterSpec(
    name="tema_long_period",
    param_type=ParameterType.INT,
    default_value=50,
    min_value=20,
    max_value=62,  # TEMA cap!
    description="TEMA long period"
)

# WRONG: Exceeds TEMA cap
ParameterSpec(
    name="tema_long_period",
    param_type=ParameterType.INT,
    default_value=50,
    min_value=20,
    max_value=80,  # EXCEEDS CAP - will cause NaN!
    description="TEMA long period"
)
```

## Parameter Access in Components

### In __init__
```python
class entry_rule(BaseComponent):
    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Extract to instance attributes for readability
        self.adx_period = self.params['adx_period']
        self.adx_threshold = self.params['adx_threshold']
        self.rsi_period = self.params['rsi_period']
        self.rsi_oversold = self.params['rsi_oversold']
```

### In Methods
```python
def generate_signal(self) -> EntrySignalOutput:
    # Use extracted attributes
    indicator_name = f'adx_{self.adx_period}'
    adx = self.get_indicator(indicator_name)

    if adx > self.adx_threshold:
        # Trading logic
        pass
```

## Complete strategy_params.py Example

```python
"""Strategy Parameters for Momentum-Trend Strategy."""
from typing import List, Dict, Any
import optuna

from echolon.strategy.parameter_architecture import (
    ComponentParameterTemplate,
    ParameterSpec,
    ParameterType,
    StrategyParameterFramework,
)


class EntryParameters(ComponentParameterTemplate):
    def get_component_name(self) -> str:
        return "entry"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            # Owned calculation parameters
            ParameterSpec(
                name="adx_period",
                param_type=ParameterType.INT,
                default_value=14,
                min_value=10,
                max_value=93,  # ADX cap
                description="ADX period [SHARED]"
            ),
            ParameterSpec(
                name="tema_short_period",
                param_type=ParameterType.INT,
                default_value=20,
                min_value=10,
                max_value=55,
                description="TEMA short period"
            ),
            ParameterSpec(
                name="tema_long_period",
                param_type=ParameterType.INT,
                default_value=50,
                min_value=20,
                max_value=62,  # TEMA cap
                description="TEMA long period"
            ),
            # Usage parameters
            ParameterSpec(
                name="adx_threshold",
                param_type=ParameterType.FLOAT,
                default_value=25.0,
                min_value=20.0,
                max_value=35.0,
                description="ADX trending threshold"
            ),
        ]


class ExitParameters(ComponentParameterTemplate):
    def get_component_name(self) -> str:
        return "exit"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec(
                name="atr_period",
                param_type=ParameterType.INT,
                default_value=14,
                min_value=10,
                max_value=21,
                description="ATR period [SHARED]"
            ),
            ParameterSpec(
                name="atr_stop_multiplier",
                param_type=ParameterType.FLOAT,
                default_value=2.0,
                min_value=1.5,
                max_value=3.5,
                description="Stop loss ATR multiplier"
            ),
        ]


class RiskParameters(ComponentParameterTemplate):
    def get_component_name(self) -> str:
        return "risk"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec(
                name="max_drawdown",
                param_type=ParameterType.FLOAT,
                default_value=0.10,
                min_value=0.05,
                max_value=0.20,
                description="Maximum drawdown limit"
            ),
        ]


class SizerParameters(ComponentParameterTemplate):
    def get_component_name(self) -> str:
        return "sizer"

    def define_parameters(self) -> List[ParameterSpec]:
        return [
            ParameterSpec(
                name="risk_per_trade",
                param_type=ParameterType.FLOAT,
                default_value=0.02,
                min_value=0.01,
                max_value=0.05,
                description="Risk per trade"
            ),
        ]


# Framework setup
_framework = StrategyParameterFramework()
_framework.register_component(EntryParameters())
_framework.register_component(ExitParameters())
_framework.register_component(RiskParameters())
_framework.register_component(SizerParameters())

DEFAULT_PARAMS = _framework.compose_default_strategy()


def optuna_search_space(trial: optuna.Trial) -> Dict[str, Any]:
    params = {}

    # Entry
    entry = {}
    entry["adx_period"] = trial.suggest_int("entry_adx_period", 10, 93)
    tema_short = trial.suggest_int("entry_tema_short_period", 10, 55)
    tema_long = trial.suggest_int("entry_tema_long_period", 20, 62)

    # CROSSOVER CONSTRAINT
    if tema_long <= tema_short + 5:
        raise optuna.TrialPruned()

    entry["tema_short_period"] = tema_short
    entry["tema_long_period"] = tema_long
    entry["adx_threshold"] = trial.suggest_float("entry_adx_threshold", 20.0, 35.0)
    entry["printlog"] = False
    params["entry_params"] = entry

    # Exit
    exit = {}
    exit["atr_period"] = trial.suggest_int("exit_atr_period", 10, 21)
    exit["atr_stop_multiplier"] = trial.suggest_float("exit_atr_stop_multiplier", 1.5, 3.5)
    exit["printlog"] = False
    params["exit_params"] = exit

    # Risk
    risk = {}
    risk["max_drawdown"] = trial.suggest_float("risk_max_drawdown", 0.05, 0.20)
    risk["printlog"] = False
    params["risk_params"] = risk

    # Sizer
    sizer = {}
    sizer["risk_per_trade"] = trial.suggest_float("sizer_risk_per_trade", 0.01, 0.05)
    sizer["printlog"] = False
    params["sizer_params"] = sizer

    return params
```
