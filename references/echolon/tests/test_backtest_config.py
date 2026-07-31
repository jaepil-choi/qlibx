"""Tests for BacktestConfig."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from echolon.config.backtest_config import BacktestConfig


def test_minimal_valid_config(tmp_path):
    cfg = BacktestConfig(
        start_date="2020-01-01",
        end_date="2025-12-31",
        strategy_dir=tmp_path / "code",
        market_data_dir=tmp_path / "market",
        indicator_dir=tmp_path / "indicators",
        results_dir=tmp_path / "results",
    )
    assert cfg.start_date == "2020-01-01"
    assert cfg.end_date == "2025-12-31"
    assert cfg.max_drawdown_pct == 15.0
    assert cfg.is_end_date is None
    assert cfg.oos_start_date is None
    assert cfg.market_research_end_date is None


def test_paths_converted_to_Path(tmp_path):
    cfg = BacktestConfig(
        start_date="2020-01-01",
        end_date="2025-12-31",
        strategy_dir=str(tmp_path / "code"),
        market_data_dir=str(tmp_path / "market"),
        indicator_dir=str(tmp_path / "indicators"),
        results_dir=str(tmp_path / "results"),
    )
    assert isinstance(cfg.strategy_dir, Path)
    assert isinstance(cfg.market_data_dir, Path)


def test_invalid_date_format_rejected(tmp_path):
    with pytest.raises(ValidationError):
        BacktestConfig(
            start_date="not-a-date",
            end_date="2025-12-31",
            strategy_dir=tmp_path / "code",
            market_data_dir=tmp_path / "market",
            indicator_dir=tmp_path / "indicators",
            results_dir=tmp_path / "results",
        )


def test_end_before_start_rejected(tmp_path):
    with pytest.raises(ValidationError):
        BacktestConfig(
            start_date="2025-01-01",
            end_date="2020-01-01",
            strategy_dir=tmp_path / "code",
            market_data_dir=tmp_path / "market",
            indicator_dir=tmp_path / "indicators",
            results_dir=tmp_path / "results",
        )


def test_oos_auto_derives_from_is_end(tmp_path):
    cfg = BacktestConfig(
        start_date="2020-01-01",
        end_date="2025-12-31",
        is_end_date="2022-12-31",
        strategy_dir=tmp_path / "code",
        market_data_dir=tmp_path / "market",
        indicator_dir=tmp_path / "indicators",
        results_dir=tmp_path / "results",
    )
    assert cfg.oos_start_date == "2023-01-01"


def test_serialization_round_trip(tmp_path):
    cfg = BacktestConfig(
        start_date="2020-01-01",
        end_date="2025-12-31",
        strategy_dir=tmp_path / "code",
        market_data_dir=tmp_path / "market",
        indicator_dir=tmp_path / "indicators",
        results_dir=tmp_path / "results",
        max_drawdown_pct=20.0,
    )
    as_dict = cfg.model_dump()
    restored = BacktestConfig.model_validate(as_dict)
    assert restored.max_drawdown_pct == 20.0
    assert restored.start_date == "2020-01-01"
