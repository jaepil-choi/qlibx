"""RSI mean reversion parameters (two-sided LONG/SHORT)."""

from typing import Any, Dict


DEFAULT_PARAMS: Dict[str, Any] = {
    # Both entry and exit need both thresholds: entry uses
    # oversold for LONG, overbought for SHORT; exit uses overbought
    # to close LONGs, oversold to close SHORTs.
    "entry_params": {
        "printlog": False,
        "rsi_period": 14,
        "oversold": 30,
        "overbought": 70,
    },
    "exit_params": {
        "printlog": False,
        "rsi_period": 14,
        "oversold": 30,
        "overbought": 70,
    },
    "risk_params": {"printlog": False},
    "sizer_params": {"printlog": False},
}


def optuna_search_space(trial):
    period = trial.suggest_int("rsi_period", 10, 20)
    oversold = trial.suggest_int("oversold", 20, 35)
    overbought = trial.suggest_int("overbought", 65, 80)
    shared = {"rsi_period": period, "oversold": oversold, "overbought": overbought}
    return {
        "entry_params": {"printlog": False, **shared},
        "exit_params": {"printlog": False, **shared},
        "risk_params": {"printlog": False},
        "sizer_params": {"printlog": False},
    }


def apply_shared_params(params):
    return params


framework = None
