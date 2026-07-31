"""Schema tests for the flat-dict indicator_list format."""
import pytest
from pydantic import ValidationError

from echolon.indicators.schema import IndicatorList, expand_param, expand_params_spec


def test_scalar_param_is_fixed_value():
    """A scalar param means a single fixed value."""
    assert expand_param(14) == [14]
    assert expand_param(2.5) == [2.5]


def test_two_int_list_is_inclusive_range():
    """[a, b] where both are ints and b > a → inclusive range, step 1."""
    assert expand_param([5, 8]) == [5, 6, 7, 8]
    assert expand_param([5, 5]) == [5]  # degenerate range


def test_float_in_list_is_explicit_values():
    """Any float forces explicit-values interpretation."""
    assert expand_param([1.5, 2.0, 2.5]) == [1.5, 2.0, 2.5]
    assert expand_param([1.5, 2.0]) == [1.5, 2.0]


def test_len_three_list_is_explicit_values():
    """3+ ints → explicit values (not a range)."""
    assert expand_param([5, 10, 20]) == [5, 10, 20]


def test_cartesian_expansion():
    """Multiple swept params → cross product."""
    spec = {"period": [15, 17], "stddev": [1.5, 2.0, 2.5]}  # [15,16,17] × [1.5,2.0,2.5]
    combos = expand_params_spec(spec)
    assert len(combos) == 3 * 3  # 9 combos
    assert {"period": 15, "stddev": 1.5} in combos
    assert {"period": 17, "stddev": 2.5} in combos


def test_schema_validates_minimal_indicator_list():
    """A list with one indicator + no params should validate."""
    IndicatorList.model_validate({"rsi": {}})


def test_schema_rejects_non_dict_entry():
    with pytest.raises(ValidationError):
        IndicatorList.model_validate({"rsi": [5, 30]})  # bare list at indicator level = wrong


def test_schema_allows_scalar_or_list_param():
    IndicatorList.model_validate({
        "rsi": {"timeperiod": [5, 30]},     # range (catalog param: timeperiod)
        "atr": {"timeperiod": 14},           # fixed
        "bbands_upper": {                    # multi-param (bbands is decomposed in registry)
            "timeperiod": [15, 25],
            "nbdevup": [1.5, 2.0, 2.5],
        },
    })
