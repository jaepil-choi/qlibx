"""v0.2.0 TradingContext should not expose the dead methods previously identified."""
import pytest

from echolon.config.markets.core.context import TradingContext


DEAD_METHODS = [
    "currency", "is_24h", "tick_size", "sessions", "design_paradigm_description",
    "trading_minutes_per_day",
    "get_session_bars", "get_phase_for_time", "get_phase_for_time_bar_aware",
    "is_trading_time", "get_phase_bars", "get_phase_buffer_bars",
    "calculate_commission", "calculate_margin", "calculate_contract_value",
    "to_dict",
]


@pytest.mark.parametrize("name", DEAD_METHODS)
def test_dead_method_removed(name):
    assert not hasattr(TradingContext, name), f"Dead method '{name}' still present"
