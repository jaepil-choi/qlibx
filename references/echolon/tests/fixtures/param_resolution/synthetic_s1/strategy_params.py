"""SYNTHETIC strategy_params fixture — scrubbed values, public-repo safe.

Reproduces the four parameter-resolution defect mechanisms without disclosing
any live strategy parameterization:
  1. canonical names that already carry their component prefix (Family-A flat
     keys) + double-prefixed Family-B default twins;
  2. an in-function SHARED sizer copy of an exit value (unrecoverable from the
     flat dict by any name-based merge);
  3. a BARE optuna key with a same-destination Family-B twin;
  4. an int distribution (CSV round-trips deliver floats; replay must re-cast).
"""
from typing import Any, Dict

DEFAULT_PARAMS: Dict[str, Any] = {
    "entry_params": {
        "alpha_period": 10,
        "entry_gate_threshold": 0.5,
        "printlog": False,
    },
    "exit_params": {
        "exit_atr_period": 12,
        "exit_down_stop_mult": 1.0,
        "exit_up_stop_mult": 2.0,
        "printlog": False,
    },
    "risk_params": {"max_drawdown_pct": 10.0, "printlog": False},
    "sizer_params": {
        "exit_down_stop_mult": 1.0,   # shared mirror of exit's value
        "trailing_mult": 3.0,
        "lots": 1,
        "printlog": False,
    },
}


def optuna_search_space(trial) -> Dict[str, Any]:
    """Mirrors the generator's shape: complete component dicts, canonical keys,
    conditional prefixing of optuna names, in-function shared copies."""
    params: Dict[str, Any] = {}

    entry_params: Dict[str, Any] = {}
    # optuna name gains the component prefix (canonical name is bare):
    entry_params["alpha_period"] = trial.suggest_int("entry_alpha_period", 5, 50)
    # canonical name ALREADY carries the prefix -> optuna name == canonical:
    entry_params["entry_gate_threshold"] = trial.suggest_float(
        "entry_gate_threshold", 0.1, 0.9
    )
    params["entry_params"] = entry_params

    exit_params: Dict[str, Any] = {}
    exit_params["exit_atr_period"] = trial.suggest_int("exit_atr_period", 5, 30)
    exit_params["exit_down_stop_mult"] = trial.suggest_float(
        "exit_down_stop_mult", 0.5, 3.0
    )
    exit_params["exit_up_stop_mult"] = 2.0  # FIXED
    params["exit_params"] = exit_params

    params["risk_params"] = {"max_drawdown_pct": 10.0}

    sizer_params: Dict[str, Any] = {}
    # Shared parameter from exit (mechanism 2):
    sizer_params["exit_down_stop_mult"] = exit_params["exit_down_stop_mult"]
    # BARE optuna name (mechanism 3):
    sizer_params["trailing_mult"] = trial.suggest_float("trailing_mult", 1.0, 5.0)
    sizer_params["lots"] = 1
    params["sizer_params"] = sizer_params

    for comp in ("entry_params", "exit_params", "risk_params", "sizer_params"):
        params[comp]["printlog"] = False
    return params
