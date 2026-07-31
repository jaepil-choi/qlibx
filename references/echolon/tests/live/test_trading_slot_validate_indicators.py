"""Phase A6 — _collect_declared_names helper on trading_slot accepts flat-dict.

Direct unit test for the pure name-extraction helper. The full TradingSlot
class has heavy live-engine dependencies and is out of scope for this unit.
"""
from echolon.live.slot.trading_slot import _collect_declared_names


def test_flat_dict_lookback_yields_bare_name():
    """Indicators with lookback: the slot checks prefix match against CSV columns,
    so the helper yields the bare name (e.g. 'rsi'), not expanded 'rsi_10' etc."""
    assert _collect_declared_names({"rsi": {"timeperiod": [10, 20]}}) == {"rsi"}


def test_flat_dict_no_params_yields_name():
    assert _collect_declared_names({"obv": {}}) == {"obv"}


def test_flat_dict_mixed():
    assert _collect_declared_names({
        "rsi": {"timeperiod": 14},
        "obv": {},
        "bbands_upper": {},
        "market_regime": {},
    }) == {"rsi", "obv", "bbands_upper", "market_regime"}


def test_empty_payload_yields_empty_set():
    assert _collect_declared_names({}) == set()


def test_non_dict_payload_returns_empty_set():
    """Guard for misshapen payloads (e.g. a list instead of a dict)."""
    assert _collect_declared_names([1, 2, 3]) == set()
