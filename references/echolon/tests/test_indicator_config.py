"""Tests for IndicatorConfig."""

from echolon.config.indicator_config import IndicatorConfig


def test_defaults():
    cfg = IndicatorConfig()
    assert cfg.interday_caps["tema"] == 62
    assert cfg.interday_caps["adx"] == 93
    assert cfg.interday_caps["default"] == 180
    assert cfg.intraday_caps["tema"] == 500
    assert cfg.intraday_caps["default"] == 1000


def test_override_caps():
    cfg = IndicatorConfig(interday_caps={"custom": 42, "default": 100})
    assert cfg.interday_caps["custom"] == 42


def test_get_cap_for_indicator():
    cfg = IndicatorConfig()
    assert cfg.get_interday_cap("tema") == 62
    assert cfg.get_interday_cap("unknown_indicator") == 180


def test_serialization_round_trip():
    cfg = IndicatorConfig(interday_caps={"custom": 42, "default": 100})
    restored = IndicatorConfig.model_validate(cfg.model_dump())
    assert restored.interday_caps["custom"] == 42
