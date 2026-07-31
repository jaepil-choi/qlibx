"""Momentum breakout parameters."""

from typing import Any, Dict


DEFAULT_PARAMS: Dict[str, Any] = {
 "entry_params": {"printlog": False, "lookback": 20},
 "exit_params": {"printlog": False, "exit_lookback": 10},
 "risk_params": {"printlog": False},
 "sizer_params": {"printlog": False},
}


def optuna_search_space(trial):
 return {
 "entry_params": {"printlog": False, "lookback": trial.suggest_int("entry_lookback", 10, 50)},
 "exit_params": {"printlog": False, "exit_lookback": trial.suggest_int("exit_lookback", 5, 20)},
 "risk_params": {"printlog": False},
 "sizer_params": {"printlog": False},
 }


def apply_shared_params(params):
 return params


framework = None
