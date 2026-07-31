"""Tests for TradingContext.from_market() constructor."""

import pytest

from echolon.config.markets.core.context import TradingContext


def test_from_market_shfe_interday():
    ctx = TradingContext.from_market(
        market="shfe",
        instrument="cu",
        frequency="interday",
        bar_size="1d",
    )
    assert ctx.market_code == "SHFE"
    assert ctx.instrument_code == "cu"
    assert ctx.frequency == "interday"
    assert ctx.bar_size == "1d"


@pytest.mark.parametrize(
    "bar_size,expected_bars_per_hour",
    [
        ("1m", 60),
        ("5m", 12),
        ("15m", 4),
        ("30m", 2),
        ("1h", 1),
        ("4h", 1),
        ("1d", 1),
    ],
)
def test_bars_per_hour(bar_size, expected_bars_per_hour):
    frequency = "interday" if bar_size == "1d" else "intraday"
    ctx = TradingContext.from_market(
        market="shfe", instrument="cu", frequency=frequency, bar_size=bar_size,
    )
    assert ctx.bars_per_hour == expected_bars_per_hour


def test_hours_to_bars_does_not_raise_attribute_error():
    ctx = TradingContext.from_market(
        market="shfe", instrument="cu", frequency="intraday", bar_size="15m",
    )
    assert ctx.hours_to_bars(2.3) == max(1, int(2.3 * 4))
    assert ctx.hours_to_bars(0.1) == 1
