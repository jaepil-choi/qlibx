"""Minimal strategy_params."""

from typing import Any, Dict

DEFAULT_PARAMS: Dict[str, Any] = {
 "entry_params": {"printlog": False},
 "exit_params": {"printlog": False},
 "risk_params": {"printlog": False},
 "sizer_params": {"printlog": False},
}


def optuna_search_space(trial):
 return {
 "entry_params": {"printlog": False},
 "exit_params": {"printlog": False},
 "risk_params": {"printlog": False},
 "sizer_params": {"printlog": False},
 }


def apply_shared_params(params):
 return params


framework = None
