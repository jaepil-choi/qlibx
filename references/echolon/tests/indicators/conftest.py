"""Shared fixtures for indicator tests."""
import pytest
from echolon.config.markets.factory import MarketFactory


@pytest.fixture
def interday_ctx():
    """Interday TradingContext for SHFE aluminum (1d bars)."""
    return MarketFactory.create(
        market="SHFE",
        instrument="al",
        frequency="interday",
        bar_size="1d",
    )
