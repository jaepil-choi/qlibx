"""Tests for OptunaConfig."""

import pytest
from pydantic import ValidationError

from echolon.config.optuna_config import OptunaConfig


def test_defaults():
    cfg = OptunaConfig()
    assert cfg.n_trials == 100
    assert cfg.n_trials_debug == 20
    assert cfg.n_jobs == -1
    assert cfg.timeout is None
    assert cfg.target == "sharpe_ratio"
    assert cfg.aggressive_memory_management is False
    assert cfg.enhanced_monitoring is True


def test_override_defaults():
    cfg = OptunaConfig(n_trials=500, target="multi_objective", n_jobs=4)
    assert cfg.n_trials == 500
    assert cfg.target == "multi_objective"
    assert cfg.n_jobs == 4


def test_invalid_target_rejected():
    with pytest.raises(ValidationError):
        OptunaConfig(target="not_a_real_target")


def test_negative_n_trials_rejected():
    with pytest.raises(ValidationError):
        OptunaConfig(n_trials=-1)


def test_serialization_round_trip():
    cfg = OptunaConfig(n_trials=200, target="drawdown")
    as_dict = cfg.model_dump()
    restored = OptunaConfig.model_validate(as_dict)
    assert restored.n_trials == 200
    assert restored.target == "drawdown"
