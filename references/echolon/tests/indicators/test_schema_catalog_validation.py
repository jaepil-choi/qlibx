"""Phase A2 — IndicatorList.model_validate wires into catalog.validate().

TDD red gate: these fail before the @model_validator is added to IndicatorList.
"""
import pytest
from pydantic import ValidationError

from echolon.indicators.schema import IndicatorList


def test_valid_payload_passes():
    IndicatorList.model_validate({"rsi": {"timeperiod": [10, 20]}, "obv": {}})


def test_unknown_indicator_name_raises_with_suggestion():
    with pytest.raises(ValidationError) as excinfo:
        IndicatorList.model_validate({"fake_rsi": {}})
    msg = str(excinfo.value)
    assert "fake_rsi" in msg
    # The error message must surface a suggestion (difflib + substring fallback)
    assert "rsi" in msg.lower()


def test_unknown_param_raises():
    with pytest.raises(ValidationError) as excinfo:
        IndicatorList.model_validate({"rsi": {"fakeperiod": 5}})
    msg = str(excinfo.value)
    assert "fakeperiod" in msg or "Unknown param" in msg


def test_lookback_min_gt_max_raises():
    with pytest.raises(ValidationError) as excinfo:
        IndicatorList.model_validate({"rsi": {"timeperiod": [20, 10]}})
    msg = str(excinfo.value)
    assert "rsi" in msg.lower()
    # The range error should be visible
    assert "min" in msg.lower() or "range" in msg.lower()


def test_multiple_errors_all_reported_in_one_validation_error():
    """Both unknown name + unknown param should surface in the same ValidationError."""
    with pytest.raises(ValidationError) as excinfo:
        IndicatorList.model_validate({
            "fake_one": {},
            "rsi": {"fakeperiod": 5},
        })
    msg = str(excinfo.value)
    assert "fake_one" in msg
    assert "fakeperiod" in msg


def test_empty_dict_still_rejected_with_existing_message():
    """A2 must not regress the existing _reject_empty validator."""
    with pytest.raises(ValidationError) as excinfo:
        IndicatorList.model_validate({})
    assert "at least one indicator" in str(excinfo.value)


def test_known_indicator_with_no_params_passes():
    """obv takes no user-tunable params — empty dict is valid."""
    IndicatorList.model_validate({"obv": {}})


def test_multiple_valid_indicators_pass():
    """Schema accepts a mix of paradigm-blind indicators. Phase G removed
    `market_regime` from echolon's catalog; classifier names are validated
    via the registry path at runtime, not at schema-validation time."""
    IndicatorList.model_validate({
        "rsi": {"timeperiod": [10, 20]},
        "atr": {"timeperiod": 14},
        "obv": {},
        "highest_high": {"timeperiod": 20},
        "bbands_upper": {"timeperiod": 20},
    })
