"""Phase A4 — merge_indicator_lists + load_indicator_list for flat-dict format."""
import json

import pytest

from echolon.indicators.utils.merge_indicators import (
    merge_indicator_lists,
    load_indicator_list,
)


def test_merge_single_config_roundtrips_unchanged():
    cfg = {"rsi": {"timeperiod": [10, 20]}, "obv": {}}
    out = merge_indicator_lists([cfg])
    assert out == cfg


def test_merge_unioned_names_across_configs():
    cfg1 = {"rsi": {"timeperiod": 14}, "obv": {}}
    cfg2 = {"atr": {"timeperiod": 10}}
    out = merge_indicator_lists([cfg1, cfg2])
    assert set(out.keys()) == {"rsi", "obv", "atr"}


def test_merge_range_min_is_minimum_across_configs():
    """Overlapping range params take union [min(mins), max(maxes)]."""
    cfg1 = {"rsi": {"timeperiod": [10, 20]}}
    cfg2 = {"rsi": {"timeperiod": [15, 30]}}
    out = merge_indicator_lists([cfg1, cfg2])
    assert out["rsi"]["timeperiod"] == [10, 30]


def test_merge_scalar_and_range_widens_to_range():
    """A scalar + a range merge into a single range covering both."""
    cfg1 = {"rsi": {"timeperiod": 14}}       # scalar 14
    cfg2 = {"rsi": {"timeperiod": [10, 20]}} # range
    out = merge_indicator_lists([cfg1, cfg2])
    assert out["rsi"]["timeperiod"] == [10, 20]


def test_merge_two_scalars_become_range_or_list():
    """Two distinct scalars for the same param get unioned into a range-or-list."""
    cfg1 = {"rsi": {"timeperiod": 10}}
    cfg2 = {"rsi": {"timeperiod": 20}}
    out = merge_indicator_lists([cfg1, cfg2])
    # Acceptable outcomes: [10, 20] (range) OR [10, 20] explicit list — both semantically valid
    assert out["rsi"]["timeperiod"] in ([10, 20],)


def test_merge_empty_params_preserved():
    cfg1 = {"obv": {}}
    cfg2 = {"obv": {}}
    out = merge_indicator_lists([cfg1, cfg2])
    assert out == {"obv": {}}


def test_merge_empty_config_list_returns_empty_dict():
    assert merge_indicator_lists([]) == {}


def test_merge_different_params_per_config_are_unioned():
    """Different params for the same indicator get unioned at the param level."""
    cfg1 = {"bbands_upper": {"timeperiod": [10, 20]}}
    cfg2 = {"bbands_upper": {"nbdevup": 2.5}}
    out = merge_indicator_lists([cfg1, cfg2])
    assert out["bbands_upper"]["timeperiod"] == [10, 20]
    assert out["bbands_upper"]["nbdevup"] == 2.5


def test_load_flat_dict_returns_flat_dict(tmp_path):
    p = tmp_path / "strategy_indicator_list.json"
    payload = {"rsi": {"timeperiod": [10, 20]}, "obv": {}}
    p.write_text(json.dumps(payload))
    out = load_indicator_list(str(p))
    assert out == payload


def test_load_rejects_invalid_payload_shape(tmp_path):
    """Arbitrary-shape payloads that aren't legacy and aren't flat-dict must fail."""
    p = tmp_path / "strategy_indicator_list.json"
    p.write_text(json.dumps({"unknown_indicator_name_xyz": {}}))
    with pytest.raises(Exception):
        load_indicator_list(str(p))
